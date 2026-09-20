import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from assist_download import CheckinError, inspect_detail, token_url, check_pdf


class DownloadTests(unittest.TestCase):
    def detail(self, owner='mine', badge='待审核'):
        return '''<title>【待确认】Test</title>
        <span class="able-head-user-vip-username">tester</span>
        <script>window.AbleActivity.start({ scope: "mine" });</script>
        <table><tr><td>求助人</td><td><a data-id="%s">tester</a></td></tr>
        <tr><td>标题</td><td>Test paper</td></tr>
        <tr><td>DOI</td><td>10.1234/test</td></tr></table>
        <li><span class="assistfile-badge">%s</span>
        <a href="/assist/download?id=abc123">paper.pdf</a></li>''' % (owner, badge)

    def test_other_users_files_are_not_downloaded(self):
        with self.assertRaises(CheckinError):
            inspect_detail(self.detail(owner='someone'), 'tester')
        self.assertEqual(inspect_detail(self.detail(), 'tester')['files'][0]['file_id'], 'abc123')
        self.assertEqual(inspect_detail(self.detail(badge='已驳回'), 'tester')['files'], [])

    def test_paid_or_untrusted_download_nodes_are_rejected(self):
        data = dict(channel='normal', transport='normal',
                    host='https://filehub2.ablesci.com/file/download',
                    token='local-test-token', output_filename='paper.pdf')
        allowed = ['filehub2.ablesci.com']
        self.assertIn('/file/download?token=', token_url(data, allowed))
        for update in [dict(channel='highspeed'), dict(transport='vip'),
                       dict(host='https://filehub2.ablesci.com.evil.example/file/download'),
                       dict(host='http://filehub2.ablesci.com/file/download'),
                       dict(host='https://user@filehub2.ablesci.com/file/download')]:
            with self.subTest(update=update), self.assertRaises(CheckinError):
                token_url(data | update, allowed)

    def test_html_and_corrupt_files_are_not_pdfs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.pdf'
            for body in [b'<html>login expired</html>', b'%PDF-1.7\ntruncated']:
                path.write_bytes(body)
                with self.assertRaises(CheckinError):
                    check_pdf(path, '10.1234/test', 'Test paper')
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=800)
            writer.write(path)
            result = check_pdf(path, '10.1234/test', 'Test paper')
            self.assertEqual(result['pages'], 1)
            self.assertFalse(result['doi_match'])
            self.assertFalse(result['title_match'])


if __name__ == '__main__':
    unittest.main()
