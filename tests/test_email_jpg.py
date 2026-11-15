import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from racevideo.email_jpg import credentials


class EmailCredentialsTests(unittest.TestCase):
    def test_private_app_config_and_environment_override(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'racevideo';config.mkdir()
            path=config/'email.env';path.write_text("GMAIL_USER=file@example.com\nGMAIL_APP_PASSWORD='abcd efgh'\n");path.chmod(0o600)
            environment={'XDG_CONFIG_HOME':folder}
            with patch.dict(os.environ,environment,clear=True):self.assertEqual(credentials(),('file@example.com','abcdefgh'))
            with patch.dict(os.environ,{**environment,'GMAIL_USER':'override@example.com'},clear=True):self.assertEqual(credentials(),('override@example.com','abcdefgh'))

    def test_rejects_credentials_readable_by_other_users(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'racevideo';config.mkdir()
            path=config/'email.env';path.write_text('GMAIL_USER=a@b.c\nGMAIL_APP_PASSWORD=secret\n');path.chmod(0o644)
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':folder},clear=True):
                with self.assertRaisesRegex(RuntimeError,'chmod 600'):credentials()


if __name__=='__main__':unittest.main()
