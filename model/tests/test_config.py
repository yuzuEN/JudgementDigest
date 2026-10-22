import json
from pathlib import Path
import tempfile
import unittest
from judgment_bert.train import parse_args


class TestConfig(unittest.TestCase):
    def test_config_loading_and_cli_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            path.write_text(json.dumps(dict(data_dir='data',output='runs',epochs=5,
                patience=3,pos_weight=True,warmup_ratio=.1,dropout=.2)))
            args=parse_args(['--config',str(path),'--epochs','2','--no-pos-weight'])
            self.assertEqual(args.epochs,2)
            self.assertEqual(args.patience,3)
            self.assertEqual(args.data_dir,Path('data'))
            self.assertFalse(args.pos_weight)
            self.assertEqual(args.warmup_ratio,.1)
            self.assertEqual(args.dropout,.2)

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            path.write_text('{"epohs": 3}')
            with self.assertRaises(SystemExit):parse_args(['--config',str(path)])

    def test_dropout_range_rejected(self):
        with self.assertRaises(SystemExit):
            parse_args(['--data-dir','data','--output','runs','--dropout','1'])
