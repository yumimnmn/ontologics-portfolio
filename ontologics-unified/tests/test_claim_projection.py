"""Claim T-Box extension (S6): ClaimIntake nodes, links to ledger boards and SHACL checks.

The private v1.7 T-Box is not in Git, so the base schema here declares exactly the
classes and predicates the chat snapshot already uses; the claim part comes only from
ontology/extensions. TEST_DATABASE_URL must be disposable.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from rdflib import RDF, URIRef

from service.ontology import OntologyCatalog, SchemaInput
from service.projections import OntologyProjector
from tests.test_claim_documents import ClaimIntakeDocumentTests, intake_content

CLAIM = "urn:ontologics:"
EXTENSION_TERMS = {"ClaimIntake", "QualityCase", "QualityScope", "ContainmentRequest", "TestRequest", "QualityTestResult",
                   "ReproductionRequirement", "claimReportsBoard", "intake_id", "case_id", "scope_id", "test_request_id", "test_result_ids"}


def base_catalog(root: Path, snapshot: dict, *, extra_classes=()):
    types = sorted({e["type"] for e in snapshot["entities"]} - EXTENSION_TERMS | set(extra_classes))
    predicates = sorted({r["predicate"] for r in snapshot["relationships"]} - EXTENSION_TERMS)
    tbox = ["@prefix v: <urn:test:v17:> .", "@prefix owl: <http://www.w3.org/2002/07/owl#> ."]
    tbox += [f"v:{t} a owl:Class ." for t in types] + [f"v:{p} a owl:ObjectProperty ." for p in predicates]
    files = {"tbox.ttl": "\n".join(tbox).encode(),
             "shapes.ttl": b"@prefix v: <urn:test:v17:> .\n@prefix sh: <http://www.w3.org/ns/shacl#> .\nv:BaseShape a sh:NodeShape ; sh:targetClass v:Nothing .\n",
             "predicate_adapters.json": json.dumps({"predicate_aliases": {}, "type_aliases": {}}).encode()}
    manifest = []
    for name, data in files.items():
        (root / name).write_bytes(data)
        manifest.append({"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest()})
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps({"files": manifest}))
    return OntologyCatalog.load(root, [SchemaInput("tbox.ttl", "tbox", "synthetic-v17"), SchemaInput("shapes.ttl", "shapes", "synthetic-v17"),
                                       SchemaInput("predicate_adapters.json", "adapters", "synthetic-v17")])


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Dedicated disposable TEST_DATABASE_URL required")
class ClaimProjectionTests(unittest.TestCase):
    def setUp(self):
        self.c = ClaimIntakeDocumentTests("runTest")
        self.addCleanup(self.c.doCleanups)
        self.c.setUp()
        self.p = self.c.p
        self.p.post(intake_content(["B-101", "B-102", "UNKNOWN-9"]))
        self.snapshot = self.p.ledger.read(self.p.author)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def project(self, snapshot, catalog):
        version = snapshot["metadata"]["server_ledger_version"]
        return OntologyProjector(catalog).project(snapshot, version, self.p.company, "INITIAL")

    def test_claim_nodes_link_to_ledger_boards_and_conform(self):
        catalog = base_catalog(self.root, self.snapshot).with_extensions()
        result = self.project(self.snapshot, catalog)
        self.assertEqual(result["validation"]["state"], "CONFORMS", result["validation"])
        self.assertEqual(result["validation"]["unmapped"], [])
        claims = [e for e in self.snapshot["entities"] if e["type"] == "ClaimIntake"]
        self.assertEqual(len(claims), 1)
        reported = [r for r in self.snapshot["relationships"] if r["predicate"] == "claimReportsBoard"]
        boards = {e["id"]: e["attributes"]["serial"] for e in self.snapshot["entities"] if e["type"] == "BoardUnit"}
        self.assertEqual(sorted(boards[r["target"]] for r in reported), ["B-101", "B-102"])  # UNKNOWN-9 is not linked
        self.assertIn(CLAIM + "ClaimIntake", result["rdf_turtle"])
        self.assertIn(CLAIM + "reported_symptom", result["rdf_turtle"])
        self.assertNotEqual(catalog.version, base_catalog(self.root, self.snapshot).version)

    def test_without_extension_the_claim_is_unmapped_and_not_ready(self):
        result = self.project(self.snapshot, base_catalog(self.root, self.snapshot))
        self.assertEqual(result["state"], "NOT_READY")
        self.assertIn("ClaimIntake", {u["term"] for u in result["validation"]["unmapped"]})

    def test_shacl_rejects_a_claim_without_symptom_or_with_a_confirmed_failure(self):
        catalog = base_catalog(self.root, self.snapshot).with_extensions()
        for change in ({"reported_symptom": None}, {"confirmed_failure": True}, {"reported_at": "2026-11-12 09:30"}, {"claimed_qty": 0}):
            with self.subTest(change=change):
                broken = deepcopy(self.snapshot)
                claim = next(e for e in broken["entities"] if e["type"] == "ClaimIntake")
                for key, value in change.items():
                    if value is None:
                        claim["attributes"].pop(key)
                    else:
                        claim["attributes"][key] = value
                self.assertEqual(self.project(broken, catalog)["validation"]["state"], "VIOLATIONS")

    def test_official_schema_with_the_same_class_wins_over_the_extension(self):
        base = base_catalog(self.root, self.snapshot, extra_classes=["ClaimIntake"])
        self.assertIs(base.with_extensions(), base)
