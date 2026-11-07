"""Detect accidental changes to sealed numerical references and their inputs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import audit
import publish


class ArtifactAuditTests(unittest.TestCase):
    def fixture(self,base):
        g=base/'golden'; g.mkdir()
        output=g/'output'; output.write_bytes(b'original NetCDF bytes')
        initial=base/'inputs'/'case'/'wrfinput'; initial.parent.mkdir(parents=True); initial.write_bytes(b'initial data')
        table=base/'runtime'/'ideal'/'table'; table.parent.mkdir(parents=True); table.write_bytes(b'physics table')
        manifest={'files':{'output':audit.digest(output)},'inputs':{'case':{'sha256':{'wrfinput':audit.digest(initial)}}},'runtime':{'ideal':{'sha256':{'table':audit.digest(table)}}}}
        mp=g/'manifest.json'; mp.write_text(json.dumps(manifest))
        (base/'golden-manifest.sha256').write_text(audit.digest(mp))
        return output,initial,table,mp

    def test_pristine_reference_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); self.fixture(base)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                audit.audit(base)
            self.assertEqual(json.loads(output.getvalue())['reference'],'golden')

    def test_corruption_of_each_artifact_is_rejected(self):
        for item in range(4):
            with self.subTest(item=item),tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); paths=self.fixture(base)
                paths[item].write_bytes(b'changed')
                with self.assertRaises(RuntimeError):
                    audit.audit(base)

    def test_separate_reference_does_not_use_original_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); self.fixture(base)
            (base/'golden').rename(base/'scaled-golden')
            (base/'golden-manifest.sha256').rename(base/'scaled-golden-manifest.sha256')
            with contextlib.redirect_stdout(io.StringIO()):
                audit.audit(base,'scaled-golden')
            (base/'scaled-golden'/'output').write_bytes(b'changed')
            with self.assertRaises(RuntimeError):
                audit.audit(base,'scaled-golden')

    def test_publication_never_overwrites_reference_or_orphaned_seal(self):
        for name in ('golden','scaled-golden'):
            for existing in ('reference','seal'):
                with self.subTest(name=name,existing=existing),tempfile.TemporaryDirectory() as tmp:
                    base=Path(tmp)
                    reference,seal=audit.reference_paths(base,name)
                    reference.mkdir() if existing=='reference' else seal.write_text('sealed')
                    with mock.patch.object(publish.run,'ART',base):
                        with self.assertRaisesRegex(RuntimeError,'never overwrites'):
                            publish.publish('first','replay',name)

    def test_reference_name_cannot_escape_artifact_directory(self):
        for name in ('../golden','nested/name','/tmp/golden','', '..'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                audit.reference_paths('/tmp/artifacts',name)


if __name__=='__main__':
    unittest.main()
