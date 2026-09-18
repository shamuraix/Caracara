// Weekly rebuild + gate + sign for every product's LTS line (Jenkins kubernetes plugin).
// The agent pod is the same ci-tools image the GitLab pipeline uses, with the
// buildkit-client-certs Secret mounted at /certs.  A second job
// (Jenkinsfile.patch) runs the daily Copa fast path with its own cron.
//
// Credentials expected in Jenkins:
//   artifactory-docker   username/password  -> ART_USR / ART_PSW
//   cosign-private-key   secret file        -> COSIGN_KEY (no OIDC identity on Jenkins)
//   cosign-password      secret text        -> COSIGN_PASSWORD (may be empty, must exist)
//   gitlab-issue-token   secret text        -> GITLAB_ISSUE_TOKEN (may be empty, must exist)
//   gitlab-sync-token    secret text        -> GITLAB_SYNC_TOKEN (api + write_repository; opens the Iron Bank sync MR)
pipeline {
  agent {
    kubernetes {
      yaml '''
apiVersion: v1
kind: Pod
spec:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
  containers:
    - name: tools
      image: artifactory.example.com/docker-atlassian-local/ci-tools:latest
      command: [sleep, infinity]
      resources:
        requests: { cpu: "1", memory: 2Gi }
        limits: { memory: 4Gi }
      volumeMounts:
        - { name: bk-certs, mountPath: /certs, readOnly: true }
  volumes:
    - { name: bk-certs, secret: { secretName: buildkit-client-certs } }
'''
      defaultContainer 'tools'
    }
  }
  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '50'))
    timeout(time: 3, unit: 'HOURS')
  }
  triggers { cron('H 2 * * 0') }  // weekly rebuild
  environment {
    ART                     = 'artifactory.example.com'
    REPO                    = 'artifactory.example.com/docker-atlassian-local'
    BUILDKIT_HOST           = 'tcp://buildkitd.buildkit.svc:1234'
    BUILDKIT_CERTS          = '/certs'
    TRIVY_DB_REPOSITORY     = 'artifactory.example.com/docker-ghcr-remote/aquasecurity/trivy-db'
    TRIVY_JAVA_DB_REPOSITORY = 'artifactory.example.com/docker-ghcr-remote/aquasecurity/trivy-java-db'
    PLATFORMS               = 'linux/amd64,linux/arm64'
    SEVERITY                = 'HIGH,CRITICAL'
    ART_CRED                = credentials('artifactory-docker')   // ART_CRED_USR / ART_CRED_PSW
    COSIGN_KEY              = credentials('cosign-private-key')   // file credential
    COSIGN_PASSWORD         = credentials('cosign-password')
    GITLAB_ISSUE_TOKEN      = credentials('gitlab-issue-token')
    GITLAB_SYNC_TOKEN       = credentials('gitlab-sync-token')
    CI_API_V4_URL           = 'https://gitlab.example.com/api/v4'
    CI_PROJECT_ID           = 'platform%2Fatlassian-images'
    CI_SERVER_HOST          = 'gitlab.example.com'
    CI_PROJECT_PATH         = 'platform/atlassian-images'
    CI_DEFAULT_BRANCH       = 'main'
    IRONBANK_FETCH          = 'vcs'                       // Artifactory VCS remote fronting repo1.dso.mil
    IRONBANK_VCS_REPO       = 'vcs-ironbank-remote'
  }
  stages {
    stage('login') {
      steps {
        sh 'crane auth login "$ART" -u "$ART_CRED_USR" -p "$ART_CRED_PSW"'
      }
    }
    stage('lint') {
      steps { sh 'scripts/lint.sh' }
    }
    // Read each LTS line's Iron Bank upstream repository (development branch,
    // via the Artifactory VCS remote) and adopt its version and checksums, so
    // this rebuild is what Iron Bank is hardening now; the MR brings git up to date.
    stage('sync-ironbank') {
      steps { sh 'scripts/sync-ironbank.sh --all --open-mr; git checkout -q -- . 2>/dev/null || true' }
    }
    stage('build+gate+sign') {
      matrix {
        axes {
          axis { name 'PRODUCT'; values 'jira', 'confluence', 'bitbucket' }
          axis { name 'LINE'; values 'lts' }  // LTS lines only (what Iron Bank hardens)
        }
        stages {
          stage('product') {
            steps {
              sh '''#!/usr/bin/env bash
                set -euo pipefail
                export OUT_DIR="out/${PRODUCT}-${LINE}"; mkdir -p "${OUT_DIR}"
                scripts/build.sh "${PRODUCT}/${LINE}" "${BUILD_NUMBER}"
                set -a; . "${OUT_DIR}/build.env"; set +a
                scripts/gate.sh "${TAG}"
                EXTRA_TAGS="${LINE}" scripts/sign.sh "${TAG%%:*}@${DIGEST}" "${VERSION}" "${OUT_DIR}/vuln.json" "${OUT_DIR}/sbom.cdx.json"
              '''
            }
          }
        }
      }
    }
  }
  post {
    always { archiveArtifacts artifacts: 'out/**/*.json, out/**/build.env', allowEmptyArchive: true }
    failure {
      sh 'scripts/open-gitlab-issue.sh "Weekly rebuild failed: build #${BUILD_NUMBER}" "See ${BUILD_URL}" || true'
    }
  }
}
