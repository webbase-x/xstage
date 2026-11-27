import unittest
from verify_test_update import PACKAGE, check_upgrade, expected, identity

OLD = {"version": "1.0.221", "build": 1221}
NEW = {"version": "1.0.222", "build": 1222}
CERT = "a" * 64


class UpdateGateTests(unittest.TestCase):
    def test_verified_identity(self):
        badging = "package: name='com.webbasex.xstage.debug' versionCode='1222' versionName='1.0.222-debug' platformBuildVersionName='15'"
        certs = f"Signer #1 certificate SHA-256 digest: {CERT}\n"
        self.assertEqual(identity(badging, certs), (*expected(NEW), CERT))
        for invalid in ("", certs + certs):
            with self.assertRaises(ValueError):
                identity(badging, invalid)

    def test_valid_update_and_immutable_rebuild(self):
        old = (*expected(OLD), CERT)
        self.assertEqual(check_upgrade(old, (*expected(NEW), CERT), OLD, NEW), CERT)
        self.assertEqual(check_upgrade(old, old, OLD, OLD), CERT)

    def test_signer_package_version_and_downgrade(self):
        old = (*expected(OLD), CERT)
        for invalid in (("com.webbasex.xstage", 1222, "1.0.222-debug", CERT),
                        (PACKAGE, 1221, "1.0.222-debug", CERT),
                        (PACKAGE, 1222, "1.0.221-debug", CERT),
                        (*expected(NEW), "b" * 64)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                check_upgrade(old, invalid, OLD, NEW)
        with self.assertRaises(ValueError):
            check_upgrade((*expected(NEW), CERT), old, NEW, OLD)
        reused = {"version": "1.0.223", "build": 1221}
        with self.assertRaises(ValueError):
            check_upgrade(old, (*expected(reused), CERT), OLD, reused)

    def test_reject_invalid_version_metadata(self):
        for build in (True, "1222", 0, 2100000001):
            with self.assertRaises(ValueError):
                expected({"version": NEW["version"], "build": build})


if __name__ == "__main__":
    unittest.main()
