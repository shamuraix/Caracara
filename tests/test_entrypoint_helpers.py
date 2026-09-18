"""Unit tests for shared/entrypoint_helpers.py and the product templates."""

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

import entrypoint_helpers as eh  # noqa: E402


class Str2BoolTests(unittest.TestCase):
    def test_truthy(self):
        for v in ("1", "true", "TRUE", "yes", "on", " y "):
            self.assertTrue(eh.str2bool(v))

    def test_falsy(self):
        for v in ("0", "false", "No", "off", "n"):
            self.assertFalse(eh.str2bool(v))

    def test_default(self):
        self.assertTrue(eh.str2bool(None, True))
        self.assertFalse(eh.str2bool("", False))

    def test_garbage(self):
        with self.assertRaises(eh.EntrypointError):
            eh.str2bool("maybe")


class ContextTests(unittest.TestCase):
    def test_driver_and_dialect_derived(self):
        ctx = eh.template_context({"ATL_DB_TYPE": "postgres72", "HOSTNAME": "node-1"})
        self.assertEqual(ctx["ATL_DB_DRIVER"], "org.postgresql.Driver")
        self.assertTrue(ctx["ATL_DB_DIALECT"].endswith("PostgreSQLDialect"))
        self.assertTrue(ctx["ATL_CONTAINER_ID"].startswith("node-1-"))

    def test_explicit_driver_wins(self):
        ctx = eh.template_context({"ATL_DB_TYPE": "mysql8", "ATL_DB_DRIVER": "x.y.Z"})
        self.assertEqual(ctx["ATL_DB_DRIVER"], "x.y.Z")

    def test_unset_secure_vars(self):
        env = {"ATL_JDBC_PASSWORD": "s3cret", "HAZELCAST_GROUP_PASSWORD": "x", "MY_TOKEN": "t", "JIRA_HOME": "/h"}
        removed = eh.unset_secure_vars(env)
        self.assertEqual(sorted(removed), ["ATL_JDBC_PASSWORD", "HAZELCAST_GROUP_PASSWORD", "MY_TOKEN"])
        self.assertEqual(list(env), ["JIRA_HOME"])


class PermTests(unittest.TestCase):
    def test_check_perms_owner(self):
        with tempfile.TemporaryDirectory() as d:
            os.chmod(d, 0o700)
            uid, gid = os.getuid(), os.getgid()
            self.assertTrue(eh.check_perms(d, uid, gid))
            self.assertFalse(eh.check_perms(d, uid + 12345, gid + 12345))
            self.assertFalse(eh.check_perms(Path(d) / "missing", uid, gid))


class TemplateRenderTests(unittest.TestCase):
    """Render every shipped template with a representative environment."""

    def render(self, product: str, template: str, env: dict) -> str:
        return eh.render_template(template, eh.template_context(env), template_dir=ROOT / product / "config")

    def test_jira_server_xml_parses(self):
        out = self.render("jira", "server.xml.j2", {
            "ATL_PROXY_NAME": "jira.example.com", "ATL_PROXY_PORT": "443",
            "ATL_TOMCAT_SCHEME": "https", "ATL_TOMCAT_SECURE": "true", "ATL_TOMCAT_CONTEXTPATH": "/jira",
            "ATL_TOMCAT_ACCESS_LOG": "true",
        })
        root = ET.fromstring(out)
        connector = root.find("./Service/Connector")
        self.assertEqual(connector.get("proxyName"), "jira.example.com")
        self.assertEqual(connector.get("port"), "8080")
        self.assertEqual(root.find("./Service/Engine/Host/Context").get("path"), "/jira")
        self.assertEqual(len(root.findall("./Service/Engine/Host/Valve")), 2)

    def test_jira_server_xml_without_proxy(self):
        out = self.render("jira", "server.xml.j2", {})
        connector = ET.fromstring(out).find("./Service/Connector")
        self.assertIsNone(connector.get("proxyName"))
        self.assertEqual(connector.get("scheme"), "http")

    def test_jira_dbconfig(self):
        out = self.render("jira", "dbconfig.xml.j2", {
            "ATL_DB_TYPE": "postgres72", "ATL_JDBC_URL": "jdbc:postgresql://db/jira",
            "ATL_JDBC_USER": "jira", "ATL_JDBC_PASSWORD": "pw", "ATL_DB_MAXACTIVE": "40",
        })
        root = ET.fromstring(out)
        self.assertEqual(root.findtext("database-type"), "postgres72")
        self.assertEqual(root.findtext("schema-name"), "public")
        self.assertEqual(root.findtext("jdbc-datasource/driver-class"), "org.postgresql.Driver")
        self.assertEqual(root.findtext("jdbc-datasource/pool-max-size"), "40")

    def test_jira_cluster_properties(self):
        out = self.render("jira", "cluster.properties.j2", {
            "JIRA_SHARED_HOME": "/shared", "JIRA_NODE_ID": "node-a", "EHCACHE_LISTENER_HOSTNAME": "10.0.0.1",
        })
        self.assertIn("jira.node.id = node-a", out)
        self.assertIn("jira.shared.home = /shared", out)
        self.assertIn("ehcache.listener.hostName = 10.0.0.1", out)
        self.assertNotIn("multicast", out)

    def test_confluence_server_xml(self):
        out = self.render("confluence", "server.xml.j2", {"ATL_TOMCAT_CONTEXTPATH": "/wiki"})
        root = ET.fromstring(out)
        paths = [c.get("path") for c in root.findall("./Service/Engine/Host/Context")]
        self.assertEqual(paths, ["/wiki", "/wiki/synchrony-proxy"])
        self.assertEqual(root.find("./Service/Connector").get("port"), "8090")

    def test_confluence_cfg_xml_clustered(self):
        out = self.render("confluence", "confluence.cfg.xml.j2", {
            "ATL_DB_TYPE": "postgresql", "ATL_JDBC_URL": "jdbc:postgresql://db/conf", "ATL_JDBC_USER": "c",
            "ATL_JDBC_PASSWORD": "p", "ATL_CLUSTERED": "true", "ATL_CLUSTER_TYPE": "kubernetes",
            "ATL_KUBERNETES_SERVICE_NAME": "confluence", "ATL_KUBERNETES_NAMESPACE": "atlassian",
            "CONFLUENCE_SHARED_HOME": "/shared",
        })
        root = ET.fromstring(out)
        props = {p.get("name"): p.text for p in root.findall("./properties/property")}
        self.assertEqual(props["hibernate.connection.driver_class"], "org.postgresql.Driver")
        self.assertEqual(props["confluence.cluster.join.type"], "kubernetes")
        self.assertEqual(props["confluence.cluster.kubernetes.service.name"], "confluence")
        self.assertEqual(props["confluence.cluster.home"], "/shared")

    def test_confluence_init_properties(self):
        out = self.render("confluence", "confluence-init.properties.j2", {"ATL_PRODUCT_HOME": "/var/conf"})
        self.assertIn("confluence.home=/var/conf", out)

    def test_bitbucket_properties(self):
        out = self.render("bitbucket", "bitbucket.properties.j2", {
            "SERVER_PROXY_NAME": "git.example.com", "JDBC_URL": "jdbc:postgresql://db/bb", "JDBC_USER": "bb",
            "JDBC_PASSWORD": "pw", "JDBC_DRIVER": "org.postgresql.Driver", "HAZELCAST_NETWORK_KUBERNETES": "true",
            "HAZELCAST_KUBERNETES_SERVICE_NAME": "bitbucket", "HAZELCAST_KUBERNETES_NAMESPACE": "atlassian",
            "ATL_BITBUCKET_PROPERTIES": "feature.public.access=false",
        })
        self.assertIn("server.port=7990", out)
        self.assertIn("server.proxy-name=git.example.com", out)
        self.assertIn("jdbc.driver=org.postgresql.Driver", out)
        self.assertIn("hazelcast.network.kubernetes.service.name=bitbucket", out)
        self.assertIn("feature.public.access=false", out)
        self.assertNotIn("setup.license", out)


class GenCfgTests(unittest.TestCase):
    def test_gen_cfg_overwrite_semantics(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out" / "confluence-init.properties"
            ctx = {"ATL_PRODUCT_HOME": "/one"}
            tdir = ROOT / "confluence" / "config"
            self.assertTrue(eh.gen_cfg("confluence-init.properties.j2", target, ctx, template_dir=tdir))
            self.assertIn("/one", target.read_text())
            self.assertEqual(oct(target.stat().st_mode & 0o777), oct(0o640))
            ctx["ATL_PRODUCT_HOME"] = "/two"
            self.assertFalse(eh.gen_cfg("confluence-init.properties.j2", target, ctx, overwrite=False, template_dir=tdir))
            self.assertIn("/one", target.read_text())
            self.assertTrue(eh.gen_cfg("confluence-init.properties.j2", target, ctx, template_dir=tdir))
            self.assertIn("/two", target.read_text())


if __name__ == "__main__":
    unittest.main()
