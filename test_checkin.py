import unittest
from unittest.mock import Mock, patch
from datetime import datetime
import checkin


def ledger(date='2026-09-20', description='签到'):
    return f'<table><tr><td>{date} 09:33:34</td><td>+10</td><td>{description}</td></tr></table>'


class CheckinTests(unittest.TestCase):
    def test_ledger_requires_today_and_exact_description(self):
        self.assertEqual(checkin.find_record(ledger(), '2026-09-20')['reward'], '+10')
        self.assertIsNone(checkin.find_record(ledger(), '2026-09-21'))
        self.assertIsNone(checkin.find_record(ledger(description='签到奖励说明'), '2026-09-20'))
        self.assertIsNone(checkin.find_record('<div>其他人 2026-09-20 完成签到 +10</div>', '2026-09-20'))

    def test_mismatched_or_expired_account_stops(self):
        with self.assertRaises(checkin.CheckinError):
            checkin.parse_profile('<form>登录</form>', 'test-user')
        with self.assertRaises(checkin.CheckinError):
            checkin.parse_profile('<span class="able-head-user-vip-username">其他账号</span>', 'test-user')

    def client(self, records):
        client = Mock()
        client.profile.return_value = ({'account': 'test-user', 'points': 158}, '<html/>')
        client.record.side_effect = records
        client.sign.return_value = {'code': 0}
        return client

    def test_already_signed_does_not_submit(self):
        client = self.client([{'time': 'today', 'reward': '+10'}])
        self.assertEqual(checkin.run(client)['status'], 'already_signed')
        client.sign.assert_not_called()

    def test_check_only_does_not_submit(self):
        client = self.client([None])
        self.assertEqual(checkin.run(client, True)['status'], 'not_signed')
        client.sign.assert_not_called()

    @patch('checkin.time.sleep')
    def test_success_response_without_ledger_is_failure(self, _sleep):
        client = self.client([None, None, None, None])
        with self.assertRaises(checkin.CheckinError):
            checkin.run(client)
        client.sign.assert_called_once()

    @patch('checkin.time.sleep')
    def test_new_sign_requires_verified_ledger(self, _sleep):
        client = self.client([None, None, {'time': 'today', 'reward': '+10'}])
        result = checkin.run(client)
        self.assertEqual(result['status'], 'signed')
        self.assertEqual(result['reward'], '+10')
        client.sign.assert_called_once()

    def test_dpapi_roundtrip(self):
        raw = b'test-not-a-real-credential'
        encrypted = checkin.dpapi(raw)
        self.assertNotIn(raw, encrypted)
        self.assertEqual(checkin.dpapi(encrypted, True), raw)


if __name__ == '__main__':
    unittest.main()
