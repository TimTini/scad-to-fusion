from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scad2fusion.cli import main


class CliTests(unittest.TestCase):
    def test_array_override_is_forwarded_to_frontend(self):
        with patch('scad2fusion.cli.generate_package') as generate:
            generate.return_value = {'validation':{'fusion_runtime':'not_run'}}
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                code = main(['source.scad','--output','Case','-D','rings=[[7,6,0]]'])
            self.assertEqual(code,0)
            self.assertEqual(generate.call_args.args[2],{'rings':[[7,6,0]]})

    def test_string_selector_is_forwarded_as_json_string(self):
        with patch('scad2fusion.cli.generate_package') as generate:
            generate.return_value = {'validation': {'fusion_runtime':'not_run'}}
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = main(['source.scad','--output','Case','-D','output_part="body"'])
            self.assertEqual(result,0)
            self.assertEqual(generate.call_args.args[2],{'output_part':'body'})

    def test_malformed_math_reports_source_location_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.scad'
            source.write_text('x=0^(-1);cube(1);')
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main([str(source), '--output', str(Path(directory) / 'Bad')])
            self.assertEqual(code, 2)
            self.assertIn('bad.scad:1:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())

    def test_unsupported_geometry_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'unsupported.scad'
            source.write_text('hull(){cube(2);sphere(3);}')
            output = Path(directory) / 'Unsupported'
            with redirect_stderr(io.StringIO()):
                code = main([str(source), '--output', str(output)])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
