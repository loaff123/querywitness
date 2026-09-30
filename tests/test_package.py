"""Packaging contract checks; CI also installs the wheel away from the source tree."""
import importlib.resources
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_project_metadata_pins_tested_parser_and_declares_cli(self):
        with (ROOT / 'pyproject.toml').open('rb') as stream:
            metadata = tomllib.load(stream)
        self.assertEqual(metadata['project']['name'], 'querywitness')
        self.assertEqual(metadata['project']['requires-python'], '>=3.11')
        self.assertEqual(metadata['project']['dependencies'], ['sqlglot==27.29.0'])
        self.assertEqual(metadata['project']['scripts']['querywitness'], 'querywitness.cli:main')
        self.assertEqual(metadata['project']['license'], 'MIT')
        self.assertIn('data/*.json', metadata['tool']['setuptools']['package-data']['querywitness'])

    def test_bundled_catalog_resource_is_available(self):
        data = importlib.resources.files('querywitness').joinpath('data/catalog.json')
        self.assertTrue(data.is_file())
        self.assertIn('count_nullable', data.read_text(encoding='utf-8'))

    def test_license_attributes_author(self):
        license_text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('MIT License', license_text)
        self.assertIn('loaff123', license_text)
        self.assertIn('Permission is hereby granted', license_text)
