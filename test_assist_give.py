import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import assist_give as give


class GiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root / 'sample.pdf'
        self.pdf.write_bytes(b'local-test-file')
        self.target = {'assist_id': 'test123', 'title': 'Sample paper', 'doi': '10.1234/test',
                       'page_title': '【求助中】Sample paper', 'can_upload': True}
        self.empty = BeautifulSoup('', 'html.parser')
        self.client = Mock()

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, submit=False, validation=None, reads=None):
        argv = ['assist_give.py', '--assist-id', 'test123', '--file', str(self.pdf)]
        if submit:
            argv.append('--submit')
        with patch.object(give, 'ROOT', self.root), patch.object(give, 'load_secret', return_value={}), \
                patch.object(give, 'Client', return_value=self.client), patch.object(give.sys, 'argv', argv), \
                patch.object(give, 'read_target', side_effect=reads or [(self.target, self.empty, 'csrf', 'mine')]), \
                patch.object(give, 'check_pdf', return_value=validation or {'pages': 1, 'doi_match': True, 'title_match': True}), \
                contextlib.redirect_stdout(io.StringIO()):
            return give.main()

    def test_preparation_never_calls_upload_api(self):
        self.assertEqual(self.invoke(), 0)
        self.client.request.assert_not_called()
        self.assertEqual(json.loads((self.root / 'give-test123.json').read_text(encoding='utf-8'))['status'], 'prepared')

    def test_mismatching_document_blocks_submission(self):
        with self.assertRaises(give.CheckinError):
            self.invoke(True, {'pages': 1, 'doi_match': False, 'title_match': True})
        self.client.request.assert_not_called()

    def test_uncertain_attempt_blocks_resubmission(self):
        (self.root / 'give-test123.json').write_text(json.dumps({'status': 'submission_pending_verification'}))
        with self.assertRaises(give.CheckinError):
            self.invoke(True)
        self.client.request.assert_not_called()

    def test_md5_success_still_requires_own_timeline_record(self):
        soup = BeautifulSoup('''<li class="layui-timeline-item"><p class="timeline-user">
            <a class="user-name" data-id="mine">tester</a></p>
            <input class="assist-file-id" value="file123">
            <span class="assistfile-badge">待审核</span>
            <div class="file-info"><a class="name">sample.pdf</a></div></li>''', 'html.parser')
        self.client.request.return_value.json.return_value = {'code': 10}
        self.assertEqual(self.invoke(True, reads=[(self.target, self.empty, 'csrf', 'mine'),
                                                  (self.target, soup, 'csrf', 'mine')]), 0)
        self.client.request.assert_called_once()
        record = json.loads((self.root / 'give-test123.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'submitted')
        self.assertEqual(record['mode'], 'md5_reuse')
        self.assertEqual(record['files'][0]['file_id'], 'file123')
        self.assertEqual(give.own_files(soup, 'someone_else'), [])


if __name__ == '__main__':
    unittest.main()
