"""Detect accidental changes to sealed numerical references and their inputs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import audit


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
            with contextlib.redirect_stdout(io.StringIO()):
                audit.audit(base)

    def test_corruption_of_each_artifact_is_rejected(self):
        for item in range(4):
            with self.subTest(item=item),tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); paths=self.fixture(base)
                paths[item].write_bytes(b'changed')
                with self.assertRaises(RuntimeError):
                    audit.audit(base)


if __name__=='__main__':
    unittest.main()
