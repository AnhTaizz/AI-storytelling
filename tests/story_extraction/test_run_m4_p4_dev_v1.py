"""Synthetic, offline behaviour tests for the DEV1/DEV2 prompt development runner."""
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from tests.story_extraction import fixture_builder as fx
from tests.story_extraction.test_run_m4_04b3g_fv1_predictions_v1 import Clock, FakeTransport
from tools.story_extraction import run_m4_p4_dev_v1 as runner
from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as protocol
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


def widened_mention_draft(draft):
    wide = deepcopy(draft)
    wide["evidence"][0]["quote"] = "Mira opened"
    return wide


def transfer_case():
    """Two synthetic transfers with the same holder receiving and then giving."""
    first, second = "ヨルがミラに灯りを渡した。", "ミラがノアに灯りを渡した。"
    ingestion, base = fx.ingest_text(first + second)
    builder = fx.Builder(ingestion, base)
    holder = builder.named(1, "ミラ")
    source, recipient, item = builder.entity(), builder.entity(), builder.entity("OBJECT")
    for sentence, giver, receiver in ((first, source, holder), (second, holder, recipient)):
        event, _ = builder.event("TRANSFER")
        builder.occurred(event, 1, sentence[:-1])
        for entity, role in ((giver, "SOURCE"), (receiver, "RECIPIENT"), (item, "THEME")):
            builder.claim(builder.prop("Participates", event=fx.V(event), participant=fx.E(entity),
                                       role=fx.ROLE(role)), [[builder.ev(1, sentence[:-1])]])
    for predicate, args in (("Possesses", {"holder": fx.E(holder)}),
                            ("Owns", {"owner": fx.E(holder)}), ("Owns", {"owner": fx.E(source)})):
        builder.claim(builder.prop(predicate, item=fx.E(item), **args),
                      [[builder.ev(1, first[:-1])]], validity=fx.OPEN)
    gold = builder.batch()
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                   scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    prepared = runner.prepare_story_extraction_draft_v1_1(context)
    return migrate_draft_v1_to_v1_1(draft), runner.CaseInput("DEV2_01", prepared, context, ()), gold


class DevelopmentRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ingestion, base, cls.gold = fx.build("c06_participant")
        scope = cls.gold["scope"]
        cls.context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                           scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
        draft, _ = canonical_gold_to_draft_v1(cls.gold, cls.context)
        cls.draft = migrate_draft_v1_to_v1_1(draft)
        cls.good = json.dumps(cls.draft)

    @contextmanager
    def fixture(self, ids=("DEV2_01",), optional=(), members=()):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            input_zip, gold_zip = root / "input.zip", root / "gold.zip"
            with ZipFile(input_zip, "w") as bundle:
                bundle.writestr("cases/", "")
                for cid in ids:
                    bundle.writestr(f"m3_sources/{cid}/unit.txt",
                                    self.context.ingestion.documents[0].source_bytes)
                for member in members:
                    bundle.writestr(member, "untrusted")
            manifest = {"cases": [{"case_id": cid,
                "canonical_annotation_member": f"cases/{cid}/canonical_annotation_batch.json",
                "gold_completeness": "COMPLETE_FOR_PROFILE",
                "required_assertion_ids": [a["id"] for a in self.gold["candidate_records"]["assertions"]
                                           if a["id"] not in optional],
                "acceptable_optional_assertion_ids": list(optional)} for cid in ids]}
            with ZipFile(gold_zip, "w") as bundle:
                bundle.writestr(runner.GOLD_MANIFEST, json.dumps(manifest))
                for row in manifest["cases"]:
                    bundle.writestr(row["canonical_annotation_member"], json.dumps(self.gold))
            for key, path in (("INPUT_SHA256", input_zip), ("GOLD_SHA256", gold_zip)):
                stack.enter_context(patch.object(runner, key, protocol.file_sha256(path)))
            # Deliberately obsolete V1 preparation: the runner must regenerate V1.1.
            loaded = [runner.CaseInput(cid, {"draft_version": "STORY_EXTRACTION_DRAFT_V1"},
                                       self.context, ()) for cid in ids]
            loader = Mock(return_value=loaded)
            clock = Clock()
            options = dict(variant="P3", dev2_input=input_zip, dev2_gold=gold_zip,
                           output_root=root / "output", cases=ids, case_loader=loader,
                           clock=clock, wait=clock.wait)
            yield options, loaded, manifest

    def transport(self, variant="P3", script=None, smoke='{"status":"ok"}', slot=protocol.CREDENTIAL_SLOT,
                  dataset="DEV2"):
        variant = variant.replace("+", "_")
        prefix = f"{runner.TASK_ID}_{'DEV1_' if dataset == 'DEV1' else ''}{variant}"
        values = {f"{prefix}_SMOKE_{slot.upper()}": [smoke]}
        for (cid, phase), raw in (script or {("DEV2_01", "PRIMARY"): self.good}).items():
            values[f"{prefix}_{cid}_{phase}"] = [raw]
        return FakeTransport(values)

    @contextmanager
    def dev1_fixture(self, completeness=("COMPLETE_FOR_PROFILE", "UNCERTAIN")):
        ids = runner.dev1_protocol.CASE_IDS[:len(completeness)]
        with self.fixture() as (opts, _, _):
            package = opts["dev2_input"].parent / "dev1.zip"
            optional = self.gold["candidate_records"]["assertions"][-1]["id"]
            rows = [{"case_id": cid, "as_of_position": self.context.as_of_position,
                     "gold_completeness": status, "acceptable_assertions": [optional],
                     "required_assertions": [a["id"] for a in self.gold["candidate_records"]["assertions"]
                                             if a["id"] != optional],
                     "narrow_span_segments": [self.gold["candidate_records"]["evidence_refs"][0]
                                               ["segment_id"]],
                     "literal_variants": [{"predicate": "Synthetic", "argument": "label",
                                           "values": ["synthetic-a", "synthetic-b"]}]}
                    for cid, status in zip(ids, completeness)]
            members = {"base_canonical_document.json": json.dumps(self.context.base_document).encode(),
                       "development_cases.jsonl": "\n".join(json.dumps(row) for row in rows).encode(),
                       "source_passage_refs.jsonl": b""}
            members.update({f"gold_batches/{cid}.json": json.dumps(self.gold).encode() for cid in ids})
            def write_members(values):
                manifest = {"files": {name: runner.dev1_protocol.sha256_bytes(raw)
                                      for name, raw in values.items()}}
                with ZipFile(package, "w") as bundle:
                    bundle.writestr(runner.DEV1_PREFIX + "manifest.json", json.dumps(manifest))
                    for name, raw in values.items():
                        bundle.writestr(runner.DEV1_PREFIX + name, raw)
            write_members(members)
            loaded = (self.context.base_document,
                      {row["case_id"]: runner.dev1_protocol.safe_case_projection(row) for row in rows},
                      {cid: self.context.passage_inputs for cid in ids}, self.context.ingestion)
            loader = Mock(return_value=loaded)
            options = {key: value for key, value in opts.items()
                       if key not in ("dev2_input", "dev2_gold", "case_loader")}
            options.update(dataset="DEV1", cases=ids, dev1_package=package,
                           dev1_ingestion_manifest=package.parent / "synthetic-manifest.json",
                           dev1_source_root=package.parent, dev1_case_loader=loader)
            with patch.object(runner, "DEV1_SHA256", protocol.file_sha256(package)):
                yield options, members, rows, write_members

    def test_prompt_composition_sources_and_request_identity(self):
        locked = protocol.prompt_material()
        self.assertEqual(runner.prompt_material("P3"), locked)
        p4 = runner.prompt_material("P4")
        old = protocol._normalized_text(protocol.SYSTEM_PREAMBLE_PATH)
        new = protocol._normalized_text(protocol.PROMPT_ROOT / "story_extraction_draft_p4_system_v1_1.txt")
        self.assertNotEqual(old, new)
        self.assertEqual(p4["primary_system"], new + locked["primary_system"][len(old):])
        self.assertEqual(p4["repair_system"], p4["primary_system"] + "\n\n" + protocol.REPAIR_SYSTEM_SUFFIX)
        for key in ("primary_user_template", "repair_user_template"):
            self.assertEqual(p4[key], locked[key])
        path6, path7 = (runner.PROMPT_ROOT / f"story_extraction_draft_{v}_system_v1_1.txt"
                        for v in ("p4r6", "p4r7"))
        original6 = path6.read_bytes()
        ending = b"\r\n" if b"\r\n" in original6 else b"\n"
        marker = "Owns = the object is the holder's property. X の Y alone never supports Possesses.".encode()
        insertion = ending.join((
            b"Possession bounds: when a TRANSFER gives the item to the holder (holder RECIPIENT, item",
            b"THEME), the holder's Possesses and Owns start at that event's anchor. When the holder",
            b"hands the item over (holder SOURCE), Possesses ends at that event's anchor; handing over",
            b"or lending never ends Owns. When the holder picks up an item nobody held, Possesses",
            b"starts at that pick-up event's anchor. Otherwise a bound stays OPEN.",
            b"",
        ))
        expected7 = original6.replace(b"STORY EXTRACTION DRAFT P4R6 V1.1",
                                      b"STORY EXTRACTION DRAFT P4R7 V1.1", 1)
        self.assertEqual(path7.read_bytes(), expected7.replace(marker + ending, marker + ending + insertion, 1))
        material6, material7 = (runner.prompt_material(v) for v in ("P4R6", "P4R7"))
        preamble6, preamble7 = (protocol._normalized_text(p) for p in (path6, path7))
        for key in ("primary_system", "repair_system"):
            self.assertEqual(material7[key], preamble7 + material6[key][len(preamble6):])
        for key in ("primary_user_template", "repair_user_template"):
            self.assertEqual(material7[key], material6[key])
        path8 = runner.PROMPT_ROOT / "story_extraction_draft_p4r8_system_v1_1.txt"
        preamble8, material8 = protocol._normalized_text(path8), runner.prompt_material("P4R8")
        self.assertTrue(preamble8.startswith("STORY EXTRACTION DRAFT P4R8 V1.1"))
        for rule in ("the AnchorDate of that event's own EVENT_TIME anchor", "そのとき, その時, 同時に (SIMULTANEOUS)",
                     "picking up or finding an\nobject nobody holds is GENERIC", "MOVEMENT needs a change of location"):
            self.assertIn(rule, preamble8)
        for key in ("primary_system", "repair_system"):
            self.assertEqual(material8[key], preamble8 + material7[key][len(preamble7):])
        self.assertEqual(runner.prompt_hashes("P4R6")["source_sha256"][path6.name],
                         protocol.sha256_bytes(original6))
        self.assertEqual(path6.read_bytes(), original6)
        with self.fixture() as (opts, _, _), tempfile.TemporaryDirectory() as tmp:
            case = runner.load_cases(opts["dev2_input"], Path(tmp), opts["cases"], opts["case_loader"])[0]
            prompt_root = Path(tmp) / "prompts"
            prompt_root.mkdir()
            for variant in ("P3", "P4", "P4R3"):
                (prompt_root / f"story_extraction_draft_{variant.lower()}_system_v1_1.txt").write_bytes(
                    f"SYNTHETIC {variant}\r\nPREAMBLE\r\n".encode())
            specs = []
            for variant in ("P3", "P4", "P4R3"):
                with self.subTest(variant=variant), patch.object(runner, "PROMPT_ROOT", prompt_root):
                    spec = runner.build_primary_spec(variant, case, "custom-model", "custom_slot")
                    specs.append(spec)
                    material = runner.prompt_material(variant)
                    if variant == "P3":
                        self.assertEqual(material, locked)
                    else:
                        preamble = protocol._normalized_text(
                            prompt_root / f"story_extraction_draft_{variant.lower()}_system_v1_1.txt")
                        self.assertEqual(material["primary_system"], preamble + locked["primary_system"][len(old):])
                        self.assertEqual(material["repair_system"], material["primary_system"] + "\n\n"
                                         + protocol.REPAIR_SYSTEM_SUFFIX)
                        for key in ("primary_user_template", "repair_user_template"):
                            self.assertEqual(material[key], locked[key])
                    self.assertEqual((spec.model, spec.credential_slot), ("custom-model", "custom_slot"))
                    self.assertEqual(spec.generation_config, {"temperature": 0, "max_output_tokens": 16384})
                    self.assertEqual(spec.schema_response_mode, protocol.SCHEMA_RESPONSE_MODE)
                    self.assertIn('"draft_version": "STORY_EXTRACTION_DRAFT_V1_1"', spec.user_prompt)
                    self.assertEqual(case.compiler_context.process_version, "v1.1")
                    self.assertNotIn("evidence_handle", spec.user_prompt)
                    hashes = runner.prompt_hashes(variant)
                    self.assertEqual(len(hashes["source_sha256"]), 6)
                    self.assertEqual(hashes["composed_sha256"]["primary_system"],
                                     protocol.sha256_text(spec.system_prompt))
            self.assertNotEqual(specs[0].job_id, specs[1].job_id)
            self.assertNotEqual(specs[0].request_fingerprint, specs[1].request_fingerprint)
            for variant in ("P5", "p4", "P", "P4_1", "P4/../P3", "P4\n", "Pé"):
                with self.subTest(invalid=variant), patch.object(runner, "PROMPT_ROOT", prompt_root):
                    for call in (runner.prompt_material, runner.prompt_hashes):
                        with self.subTest(call=call.__name__), self.assertRaises(runner.DevelopmentError):
                            call(variant)

    def test_hash_refusal_and_selection_validation(self):
        with self.fixture() as (opts, _, _):
            for name in ("dev2_input", "dev2_gold"):
                with self.subTest(archive=name), patch.object(runner, "INPUT_SHA256" if name == "dev2_input"
                                                             else "GOLD_SHA256", "0" * 64):
                    fake = Mock(side_effect=AssertionError("provider called"))
                    with self.assertRaisesRegex(runner.DevelopmentError, "hash mismatch"):
                        runner.execute(**opts, mode="run", transport=fake)
                    fake.assert_not_called()
                    opts["case_loader"].assert_not_called()
            for cases in ([], ["DEV2_00"], ["DEV2_01", "DEV2_01"]):
                with self.subTest(cases=cases), self.assertRaises(runner.DevelopmentError):
                    runner.selected_cases(cases)
            self.assertEqual(runner.selected_cases(None), runner.CASE_IDS)
            with self.assertRaises(runner.DevelopmentError):
                runner.execute(**opts, mode="invalid")
            for overrides in ({"dataset": "UNKNOWN"}, {"dev2_input": None}, {"dev2_gold": None}):
                with self.subTest(overrides=overrides), self.assertRaises(runner.DevelopmentError):
                    runner.execute(**{**opts, **overrides})
        with self.dev1_fixture() as (opts, _, _, _):
            for key in ("dev1_package", "dev1_ingestion_manifest", "dev1_source_root"):
                with self.subTest(missing=key), self.assertRaises(runner.DevelopmentError):
                    runner.execute(**{**opts, key: None})
            with patch.object(runner, "DEV1_SHA256", "0" * 64):
                with self.assertRaisesRegex(runner.DevelopmentError, "hash mismatch"):
                    runner.execute(**opts)
            opts["dev1_case_loader"].assert_not_called()
            self.assertEqual(runner.selected_cases(None, "DEV1"), runner.dev1_protocol.CASE_IDS)
            for ids in ([], ["DEV2_01"], ["M4DEV_01", "M4DEV_01"]):
                with self.subTest(dev1_ids=ids), self.assertRaises(runner.DevelopmentError):
                    runner.selected_cases(ids, "DEV1")

    def test_preflight_selects_and_builds_one_spec_without_provider_work(self):
        with self.fixture(("DEV2_01", "DEV2_03")) as (opts, _, _):
            fake = Mock(side_effect=AssertionError("provider called"))
            for ids in (("DEV2_03",), ("DEV2_03", "DEV2_01")):
                with self.subTest(ids=ids), patch.object(runner, "build_primary_spec",
                                                       wraps=runner.build_primary_spec) as build:
                    result = runner.execute(**{**opts, "cases": ids}, transport=fake)
                    self.assertEqual((result["case_count"], result["primary_specs"]), (len(ids), len(ids)))
                    self.assertEqual([call.args[1].case_id for call in build.call_args_list], list(ids))
                    self.assertEqual(result["prompt_hashes"], runner.prompt_hashes("P3"))
                    self.assertEqual(result["status"], "PREFLIGHT_PASS")
            fake.assert_not_called()
            self.assertFalse(opts["output_root"].exists())

    def test_existing_names_use_only_affirmed_base_facts_and_compiler_handles(self):
        ingestion, base = fx.ingest_text("Mira greeted Captain Mira and the stranger. Niko watched.")
        builder = fx.Builder(ingestion, base)
        mira = builder.named(1, "Mira")
        builder.named(1, "Captain Mira", entity=mira)
        builder.named(1, "Mira", entity=mira)  # Duplicate surface forms collapse.
        niko = builder.entity()
        unnamed = builder.named(1, "the stranger")
        for entity, name, kind, polarity in (
                (mira, "Mira", "GIVEN", "AFFIRMED"),
                (mira, "Captain Mira", "TITLE", "AFFIRMED"),
                (mira, "Mira", "GIVEN", "AFFIRMED"),
                (mira, "Mira", "NICKNAME", "AFFIRMED"),
                (mira, "Wrong name", "GIVEN", "NEGATED"),
                (mira, "Uncertain name", "GIVEN", "OPEN"),
                (niko, "Niko", "GIVEN", "AFFIRMED"),
                (unnamed, "Rejected name", "GIVEN", "NEGATED")):
            builder.claim(builder.prop("NamedAs", entity=fx.E(entity), name=fx.S(name),
                                      name_kind=fx.TOK("name_kind", kind)),
                          [[builder.ev(1)]], polarity=polarity, validity=fx.OPEN)
        builder.prop("NamedAs", entity=fx.E(mira), name=fx.S("Unasserted name"),
                     name_kind=fx.TOK("name_kind", "GIVEN"))
        for polarity in ("NEGATED", "OPEN"):
            mention = builder.mention(1, "Niko")
            builder.claim(builder.prop("RefersTo", entity=fx.E(mira), mention=fx.M(mention)),
                          [[builder.ev(1)]], polarity=polarity)
        builder.claim(builder.prop("IdentityKnown", entity=fx.E(mira)), [[builder.ev(1)]])
        builder.records["propositions"].append({"id": "synthetic-placeholder", "placeholder": True})
        builder.claim("synthetic-placeholder", [[builder.ev(1)]])
        scope = builder.batch()["scope"]
        for collection, records in builder.records.items():
            base[collection].extend(records)
        context = replace(self.context, base_document=base, ingestion=ingestion,
                          passage_inputs=scope["passage_inputs"], as_of_position=scope["as_of_position"])
        original = deepcopy(context)
        prepared = runner.prepare_story_extraction_draft_v1_1(context)
        _, mapping = runner.compiler._context_maps(context)
        expected = deepcopy(prepared)
        for handle, (collection, rid) in mapping.items():
            if collection == "entities" and rid in (mira, niko):
                expected["existing_context"][handle].update(
                    names=([{"name": "Captain Mira", "name_kind": "TITLE"},
                            {"name": "Mira", "name_kind": "GIVEN"},
                            {"name": "Mira", "name_kind": "NICKNAME"}] if rid == mira else
                           [{"name": "Niko", "name_kind": "GIVEN"}]),
                    mention_forms=["Captain Mira", "Mira"] if rid == mira else [])
            if collection == "entities" and rid == unnamed:
                self.assertEqual(expected["existing_context"][handle], {"kind": "CHARACTER"})
        # Reordering every base collection must preserve the compiler's handle identities.
        for reverse in (False, True):
            reordered = {key: list(reversed(value)) if reverse and isinstance(value, list) else value
                         for key, value in base.items()}
            reordered_context = replace(context, base_document=reordered)
            for dataset in ("DEV1", "DEV2"):
                fixture = self.dev1_fixture() if dataset == "DEV1" else self.fixture()
                with self.subTest(reverse=reverse, dataset=dataset), fixture as values:
                    opts = values[0]
                    if dataset == "DEV1":
                        old = opts["dev1_case_loader"].return_value
                        opts["dev1_case_loader"].return_value = (
                            reordered, old[1], {cid: context.passage_inputs for cid in opts["cases"]}, ingestion)
                    else:
                        opts["case_loader"].return_value = [runner.CaseInput(
                            "DEV2_01", {}, reordered_context, ())]
                    for enabled in (False, True):
                        with self.subTest(enabled=enabled), patch.object(
                                runner, "build_primary_spec", wraps=runner.build_primary_spec) as build:
                            result = runner.execute(**opts, existing_names=enabled)
                            self.assertEqual(result["existing_names"], enabled)
                            for call in build.call_args_list:
                                case = call.args[1]
                                self.assertEqual(case.prepared_input, expected if enabled else prepared)
                                self.assertEqual(case.compiler_context.base_document, reordered)
                                self.assertEqual(runner.compiler._context_maps(case.compiler_context)[1], mapping)
        self.assertEqual(context.base_document, original.base_document)
        self.assertEqual(prepared, runner.prepare_story_extraction_draft_v1_1(context))

    def test_run_outcomes_artifacts_and_locked_resume(self):
        schema = {**self.draft, "unexpected": True}
        compiler = deepcopy(self.draft)
        compiler["evidence"][0]["quote"] = "SYNTHETIC_MISMATCH"
        scenarios = [("success", self.good, None, True), ("json repair", "{", self.good, True),
                     ("schema repair", json.dumps(schema), self.good, True),
                     ("compiler repair", json.dumps(compiler), self.good, True),
                     ("double failure", "{", "{", False), ("empty primary", "", self.good, True),
                     ("transport", None, None, False), ("repair transport", "{", None, False)]
        for variant in ("P3", "P4"):
            for label, primary, repair, valid in scenarios:
                with self.subTest(variant=variant, scenario=label), self.fixture() as (opts, _, _):
                    opts["variant"] = variant
                    script = {("DEV2_01", "PRIMARY"): primary}
                    if primary is not None and primary != self.good:
                        script["DEV2_01", "REPAIR_1"] = repair
                    fake = self.transport(variant, script)
                    score = runner.execute(**opts, mode="run", transport=fake)
                    before = list(fake.calls)
                    again = runner.execute(**opts, mode="run", transport=fake)
                    self.assertEqual(fake.calls, before)
                    self.assertEqual(again["summary"], score["summary"])
                    self.assertEqual(score["summary"]["layers"]["L0_structural_valid"], int(valid))
                    directory = opts["output_root"] / variant / "artifacts" / "DEV2_01"
                    saved = json.loads((directory / "validation.json").read_text())
                    self.assertEqual(saved["repair_used"], primary is not None and primary != self.good)
                    if primary is not None:
                        self.assertEqual((directory / "primary_raw.txt").read_text(), primary)
                    if valid:
                        self.assertTrue((directory / "compiled_batch.json").is_file())
                        batch = json.loads((directory / "compiled_batch.json").read_text())
                        self.assertEqual(batch["candidate_records"]["extraction_provenance"][0]["process_id"],
                                         f"{runner.TASK_ID}_{variant}")
                        phase = "primary" if primary == self.good else "repair_1"
                        self.assertEqual(json.loads((directory / f"{phase}_draft.json").read_text()), self.draft)
                    else:
                        self.assertEqual(score["rows"][0]["evaluation"]["case_outcome"], "FAIL")
                        self.assertFalse((directory / "compiled_batch.json").exists())
                    self.assertTrue((opts["output_root"] / variant / "score.json").is_file())

    def test_interrupted_artifact_write_resumes_locked_response_and_variants_are_isolated(self):
        with self.fixture() as (opts, _, _):
            fake = self.transport()
            with patch.object(runner, "validate_raw", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    runner.execute(**opts, mode="run", transport=fake)
            before = list(fake.calls)
            runner.execute(**opts, mode="run", transport=fake)
            self.assertEqual(fake.calls, before)
            other = self.transport("P4")
            runner.execute(**{**opts, "variant": "P4"}, mode="run", transport=other)
            self.assertTrue(set(j for j, _ in before).isdisjoint(j for j, _ in other.calls))
            for variant in ("P3", "P4"):
                self.assertEqual(len(list((opts["output_root"] / variant / "checkpoints" / "jobs").glob("*.json"))), 2)

    def test_smoke_refusal_overrides_and_prompt_change_guard(self):
        for raw in ('{"status":"no"}', "invalid json", None):
            with self.subTest(raw=raw), self.fixture() as (opts, _, _):
                fake = self.transport(smoke=raw)
                with self.assertRaisesRegex(runner.DevelopmentError, "smoke"):
                    runner.execute(**opts, mode="run", transport=fake)
                self.assertTrue(all("SMOKE" in job for job, _ in fake.calls))
        with self.fixture() as (opts, _, _):
            fake = self.transport(slot="custom_slot")
            runner.execute(**opts, mode="run", transport=fake, model="custom-model", credential_slot="custom_slot")
            self.assertIn("CUSTOM_SLOT", fake.calls[0][0])
            with self.assertRaises(runner.CheckpointIntegrityError):
                runner.execute(**opts, mode="run", transport=fake, model="changed-model", credential_slot="custom_slot")
        with self.fixture() as (opts, _, _):
            fake = Mock()
            hashes = runner.prompt_hashes("P3")
            with patch.object(runner, "prompt_hashes", side_effect=[hashes, {}]):
                with self.assertRaisesRegex(runner.CheckpointIntegrityError, "sources changed"):
                    runner.execute(**opts, mode="run", transport=fake)
            fake.assert_not_called()

    def test_real_scoring_optional_ids_aggregation_conventions_and_public_summary(self):
        optional = self.gold["candidate_records"]["assertions"][-1]["id"]
        draft = deepcopy(self.draft)
        draft["assertions"].pop()
        ids = ("DEV2_01", "DEV2_02", "DEV2_03")
        with self.fixture(ids, (optional,)) as (opts, _, _):
            fake = self.transport(script={(ids[0], "PRIMARY"): json.dumps(draft),
                                          (ids[1], "PRIMARY"): self.good,
                                          (ids[2], "PRIMARY"): "{", (ids[2], "REPAIR_1"): "{"})
            with patch.object(runner.scoring.evaluator, "evaluate_case",
                              wraps=runner.scoring.evaluator.evaluate_case) as evaluate:
                result = runner.execute(**opts, mode="run", transport=fake)
            for call in evaluate.call_args_list:
                self.assertEqual(call.kwargs["case_spec"], {
                    "mode": "REAL_SOURCE", "gold_completeness": "COMPLETE_FOR_PROFILE",
                    "acceptable_assertion_ids": [optional], "adjudications": []})
            metrics = result["summary"]
            self.assertEqual(metrics["cases"], 3)
            self.assertEqual(metrics["cases_by_completeness"],
                             {"COMPLETE_FOR_PROFILE": 3, "INCOMPLETE": 0, "UNCERTAIN": 0})
            self.assertEqual(metrics["cases_structurally_invalid"], 1)
            self.assertEqual(metrics["full_canonical_case_success_count"], 2)
            self.assertEqual(metrics["assertion_recall"], 1.0)
            self.assertEqual(metrics["assertion_precision"], 1.0)
            self.assertEqual(metrics["failure_code_counts"], {"CANONICAL_CONFORMANCE_FAILURE": 1})
            self.assertEqual(result["conventions_cases_checked"], 2)
            for rule in runner.RULE_IDS:
                self.assertEqual(result["conventions_counts"][rule], sum(
                    r["conventions"]["counts"][rule] for r in result["rows"] if r["conventions"]))
            no_provider = Mock(side_effect=AssertionError("score contacted provider"))
            again = runner.execute(**opts, mode="score", transport=no_provider)
            no_provider.assert_not_called()
            self.assertEqual(again["summary"], metrics)
            result["summary"]["gold_ids"] = [optional]
            result["summary"]["assertion_precision"] = "PRIVATE_TEXT"
            public = json.dumps(runner.public_summary(result))
            for secret in (optional, "DEV2_01", "PRIVATE_TEXT", "gold_ids", "candidate_records"):
                self.assertNotIn(secret, public)
            self.assertIn("CANONICAL_CONFORMANCE_FAILURE", public)
            directory = opts["output_root"] / "P3" / "artifacts" / ids[0]
            (directory / "compiled_batch.json").write_text("{}")
            with self.assertRaisesRegex(runner.CheckpointIntegrityError, "hash mismatch"):
                runner.execute(**opts, mode="score", transport=no_provider)
            with self.assertRaisesRegex(runner.CheckpointIntegrityError, "request differs"):
                runner.execute(**opts, mode="score", model="different-model", transport=no_provider)

        for scenario in ("success", "repair", "structural failure", "missing source"):
            with self.subTest(scenario=scenario), self.dev1_fixture() as (opts, _, rows, _):
                ids = opts["cases"]
                fake = self.transport(dataset="DEV1", script={
                    (cid, phase): raw for cid in ids for phase, raw in (
                        [("PRIMARY", self.good)] if scenario in ("success", "missing source") else
                        [("PRIMARY", "{"), ("REPAIR_1", "{" if scenario == "structural failure" else self.good)])})
                original_loader = runner.load_dev1_cases
                def load(*args):
                    cases, gold = original_loader(*args)
                    for case in cases:
                        self.assertEqual(case.compiler_context.profile_id, self.gold["scope"]["profile_id"])
                        self.assertEqual(case.compiler_context.process_version, "v1.1")
                        self.assertEqual(case.compiler_context.process_id, f"{runner.TASK_ID}_DEV1_P3")
                        self.assertEqual(case.compiler_context.run_id, f"DEV1_P3_{case.case_id}_PRIMARY")
                        self.assertEqual(case.sources, tuple(doc.source_bytes for doc in self.context.ingestion.documents))
                        self.assertNotIn("gold_completeness", json.dumps(case.prepared_input))
                    return ([replace(case, sources=()) for case in cases]
                            if scenario == "missing source" else cases), gold
                with patch.object(runner, "load_dev1_cases", side_effect=load), patch.object(
                        runner.scoring.evaluator, "evaluate_case", wraps=runner.scoring.evaluator.evaluate_case) as evaluate:
                    preflight = runner.execute(**opts, transport=fake)
                    self.assertEqual((preflight["dataset"], preflight["case_count"]), ("DEV1", 2))
                    self.assertFalse(fake.calls)
                    self.assertFalse(opts["output_root"].exists())
                    result = runner.execute(**opts, mode="run", transport=fake)
                    calls = list(fake.calls)
                    scored = runner.execute(**opts, mode="score", transport=fake)
                    resumed = runner.execute(**opts, mode="run", transport=fake)
                    self.assertEqual(fake.calls, calls)
                self.assertEqual(scored["summary"], result["summary"])
                self.assertEqual(resumed["summary"], result["summary"])
                self.assertEqual(result["summary"]["cases_by_completeness"],
                                 {"COMPLETE_FOR_PROFILE": 1, "INCOMPLETE": 0, "UNCERTAIN": 1})
                if scenario == "structural failure":
                    evaluate.assert_not_called()
                else:
                    for call, row in zip(evaluate.call_args_list, rows * 3):
                        spec = call.kwargs["case_spec"]
                        self.assertEqual(spec, {"mode": "REAL_SOURCE", "adjudications": [],
                            "gold_completeness": row["gold_completeness"],
                            "acceptable_assertion_ids": row["acceptable_assertions"],
                            "narrow_span_segments": row["narrow_span_segments"],
                            "literal_variants": row["literal_variants"]})
                for row, expected in zip(result["rows"], rows):
                    self.assertEqual(row["evaluation"]["gold_completeness"], expected["gold_completeness"])
                    self.assertEqual(row["conventions"] is None,
                                     scenario in ("missing source", "structural failure"))
                    self.assertEqual(row["conventions_reason"],
                                     "SOURCE_OR_SPAN_UNVERIFIABLE" if scenario == "missing source" else None)
                public = runner.public_summary(result)
                self.assertEqual(public["aggregate"]["cases_by_completeness"],
                                 result["summary"]["cases_by_completeness"])
                self.assertNotIn(ids[0], json.dumps(public))
                root = opts["output_root"] / "DEV1" / "P3"
                self.assertTrue((root / "score.json").is_file())
                expected_jobs = {f"{runner.TASK_ID}_DEV1_P3_SMOKE_{protocol.CREDENTIAL_SLOT.upper()}"}
                expected_jobs.update(f"{runner.TASK_ID}_DEV1_P3_{cid}_{phase}" for cid in ids
                                     for phase in (["PRIMARY"] if scenario in ("success", "missing source")
                                                   else ["PRIMARY", "REPAIR_1"]))
                self.assertEqual({job for job, _ in fake.calls}, expected_jobs)
                dev2 = self.transport()
                with self.fixture() as (dev2_opts, _, _):
                    dev2_result = runner.execute(**{**dev2_opts, "output_root": opts["output_root"]},
                                                 mode="run", transport=dev2)
                self.assertEqual(dev2_result["dataset"], "DEV2")
                self.assertTrue((opts["output_root"] / "P3" / "score.json").is_file())
                self.assertTrue(expected_jobs.isdisjoint(job for job, _ in dev2.calls))

    def test_input_loader_and_gold_refusals(self):
        for member in ("../escape.txt", "gold/leak.txt"):
            with self.subTest(member=member), self.fixture(members=(member,)) as (opts, _, _):
                with self.assertRaises(runner.Dev2PredictionError):
                    runner.execute(**opts)
                opts["case_loader"].assert_not_called()
        with self.fixture() as (opts, loaded, manifest):
            for bad in ([], loaded + loaded):
                with self.subTest(loaded=len(bad)):
                    opts["case_loader"].return_value = bad
                    with self.assertRaisesRegex(runner.DevelopmentError, "loader case identity"):
                        runner.execute(**opts)
            for problem in ("duplicate case", "missing case", "partition", "completeness"):
                bad = deepcopy(manifest)
                if problem == "duplicate case":
                    bad["cases"] *= 2
                elif problem == "missing case":
                    bad["cases"] = []
                elif problem == "partition":
                    bad["cases"][0]["required_assertion_ids"] = []
                else:
                    bad["cases"][0]["gold_completeness"] = "INVALID"
                with self.subTest(problem=problem), ZipFile(opts["dev2_gold"], "w") as bundle:
                    bundle.writestr(runner.GOLD_MANIFEST, json.dumps(bad))
                    bundle.writestr(manifest["cases"][0]["canonical_annotation_member"], json.dumps(self.gold))
                with self.assertRaises(runner.DevelopmentError):
                    runner.read_gold(opts["dev2_gold"], opts["cases"])
        for problem in ("input hash", "gold hash", "missing hash", "missing member", "duplicate member",
                        "duplicate case", "missing case", "completeness", "loader cases", "loader refs"):
            with self.subTest(dev1_problem=problem), self.dev1_fixture() as (opts, members, rows, write):
                cid = opts["cases"][0]
                if problem in ("duplicate case", "missing case", "completeness"):
                    if problem == "duplicate case":
                        rows += rows
                    elif problem == "missing case":
                        rows = []
                    else:
                        rows[0]["gold_completeness"] = "INVALID"
                    members["development_cases.jsonl"] = "\n".join(json.dumps(row) for row in rows).encode()
                write(members)
                if problem in ("input hash", "gold hash", "missing hash", "missing member", "duplicate member"):
                    member = "base_canonical_document.json" if problem == "input hash" else f"gold_batches/{cid}.json"
                    prefix = runner.DEV1_PREFIX
                    with ZipFile(opts["dev1_package"]) as bundle:
                        content = {name: bundle.read(name) for name in bundle.namelist()}
                    if problem in ("input hash", "gold hash"):
                        content[prefix + member] = b"{}"
                    elif problem == "missing hash":
                        manifest = json.loads(content[prefix + "manifest.json"])
                        del manifest["files"][member]
                        content[prefix + "manifest.json"] = json.dumps(manifest).encode()
                    elif problem == "missing member":
                        del content[prefix + member]
                    with ZipFile(opts["dev1_package"], "w") as bundle:
                        for name, raw in content.items():
                            bundle.writestr(name, raw)
                        if problem == "duplicate member":
                            with self.assertWarns(UserWarning):
                                bundle.writestr(prefix + member, content[prefix + member])
                elif problem in ("loader cases", "loader refs"):
                    loaded = list(opts["dev1_case_loader"].return_value)
                    loaded[1 if problem == "loader cases" else 2] = {}
                    opts["dev1_case_loader"].return_value = tuple(loaded)
                with patch.object(runner, "DEV1_SHA256", protocol.file_sha256(opts["dev1_package"])):
                    with self.assertRaises(runner.DevelopmentError):
                        runner.execute(**opts)
                if problem not in ("loader cases", "loader refs"):
                    opts["dev1_case_loader"].assert_not_called()

    def test_quote_options_isolate_jobs_save_raw_and_resolved_and_record_metadata(self):
        noisy = deepcopy(self.draft)
        noisy["evidence"][0]["quote"] = "\n".join(noisy["evidence"][0]["quote"])
        roots, jobs = set(), set()
        with self.fixture() as (opts, _, _):
            for qr, rb, en, am in ((qr, rb, en, am) for qr in (False, True)
                                   for rb in (False, True) for en in (False, True) for am in (False, True)):
                with self.subTest(qr=qr, rb=rb, en=en, am=am):
                    label = "P3" + ("+QR" if qr else "") + ("+RB" if rb else "") + ("+EN" if en else "") + ("+AM" if am else "")
                    fake = self.transport(label, script={
                        ("DEV2_01", "PRIMARY"): "{", ("DEV2_01", "REPAIR_1"): json.dumps(noisy)})
                    score = runner.execute(**opts, mode="run", transport=fake,
                                           quote_resolution=qr, rich_repair_blockers=rb, existing_names=en, anchor_mentions=am)
                    self.assertEqual((score["quote_resolution"], score["rich_repair_blockers"]), (qr, rb))
                    self.assertEqual(score["existing_names"], en)
                    self.assertEqual(score.get("anchor_mentions"), True if am else None)
                    self.assertEqual(score["rows"][0]["terminal_status"],
                                     "STRUCTURAL_VALID" if qr else "DRAFT_COMPILER_FAILURE")
                    root = opts["output_root"] / label
                    roots.add(root)
                    new_jobs = {job for job, _ in fake.calls}
                    self.assertEqual(new_jobs, {f"{runner.TASK_ID}_{label.replace('+', '_')}_{suffix}"
                                               for suffix in (f"SMOKE_{protocol.CREDENTIAL_SLOT.upper()}",
                                                              "DEV2_01_PRIMARY", "DEV2_01_REPAIR_1")})
                    self.assertTrue(jobs.isdisjoint(new_jobs))
                    jobs.update(new_jobs)
                    saved = root / "artifacts" / "DEV2_01"
                    self.assertEqual(json.loads((saved / "repair_1_draft.json").read_text()), noisy)
                    validation = json.loads((saved / "validation.json").read_text())
                    if qr:
                        expected = deepcopy(self.draft)
                        expected["evidence"][0].pop("occurrence", None)
                        self.assertEqual(json.loads((saved / "repair_1_resolved_draft.json").read_text()), expected)
                        self.assertEqual(validation["validation"]["quote_resolution"]["evidence"]
                                         ["RESOLVED_NORMALIZED"], 1)
                    else:
                        self.assertNotIn("quote_resolution", validation["validation"])
                        self.assertEqual((saved / "repair_1_resolved_draft.json").exists(), am)
                    if am:
                        self.assertEqual(validation["validation"]["mention_anchoring"]["mentions"]["ALREADY_LOCATED"],
                                         len(self.draft["mentions"]))
                    else:
                        self.assertNotIn("mention_anchoring", validation["validation"])
                    stored_score = json.loads((root / "score.json").read_text())
                    self.assertEqual(stored_score["quote_resolution"], qr)
                    self.assertEqual(stored_score["existing_names"], en)
                    calls = list(fake.calls)
                    runner.execute(**opts, mode="score", transport=fake,
                                   quote_resolution=qr, rich_repair_blockers=rb, existing_names=en, anchor_mentions=am)
                    self.assertEqual(fake.calls, calls)
            self.assertEqual(len(roots), 16)
            primary_opts = {**opts, "output_root": opts["output_root"] / "primary"}
            fake = self.transport("P3+QR", script={("DEV2_01", "PRIMARY"): json.dumps(noisy)})
            runner.execute(**primary_opts, mode="run", quote_resolution=True, transport=fake)
            saved = primary_opts["output_root"] / "P3+QR" / "artifacts" / "DEV2_01"
            self.assertEqual(json.loads((saved / "primary_draft.json").read_text()), noisy)
            self.assertEqual(json.loads((saved / "primary_resolved_draft.json").read_text()), expected)
            self.assertFalse(json.loads((saved / "validation.json").read_text())["repair_used"])

    def test_anchoring_compiles_preserves_originals_and_replays_all_attempts(self):
        bad = deepcopy(self.draft)
        bad["mentions"][0]["occurrence"] = 99
        bad["mentions"].append({**bad["mentions"][0], "handle": "M99", "quote": "Synthetic ghost"})
        # Keep an unreferenced entity and an unreferenced, located mention to
        # establish the compiler's actual policy rather than assume it.
        bad["entities"].append({"handle": "E_NEW_99", "kind": "CHARACTER"})
        bad["mentions"].append({**self.draft["mentions"][0], "handle": "M98"})
        bad["propositions"].append({"handle": "PROP99", "predicate": "RefersTo", "args": {
            "mention": {"kind": "MENTION", "handle": "M99"},
            "entity": {"kind": "ENTITY", "handle": "E_NEW_99"}}})
        bad["assertions"].append({**deepcopy(bad["assertions"][0]), "handle": "A99",
                                   "proposition_handle": "PROP99"})
        prepared = runner.prepare_story_extraction_draft_v1_1(self.context)
        case = runner.CaseInput("DEV2_01", prepared, self.context, ())
        raw = json.dumps(bad)
        _, _, initial = runner.validate_raw(raw, self.context)
        self.assertFalse(initial["pass"])
        for qr in (False, True):
            with self.subTest(quote_resolution=qr):
                original, resolved, batch, validation = runner.validate_attempt(
                    raw, case, quote_resolution=qr, anchor_mentions=True)
                self.assertEqual(original, bad)
                self.assertTrue(validation["pass"], validation)
                self.assertIsNotNone(batch)
                self.assertEqual(validation["mention_anchoring"]["removed"],
                                 {"mentions": 1, "propositions": 1, "assertions": 1})
                self.assertEqual(validation["mention_anchoring"]["mentions"]["ANCHORED_TO_EVIDENCE"], 1)
                self.assertIn({"handle": "E_NEW_99", "kind": "CHARACTER"}, resolved["entities"])
                self.assertIn("M98", [m["handle"] for m in resolved["mentions"]])
                self.assertTrue(runner.validate_raw(json.dumps(resolved), self.context)[2]["pass"])
                # Both primary and repair validation must apply the transform.
                for phase in ("primary", "repair_1"):
                    with self.subTest(phase=phase), self.fixture() as (opts, _, _):
                        flags = dict(quote_resolution=qr, anchor_mentions=True)
                        label = "P3" + ("+QR" if qr else "") + "+AM"
                        script = {("DEV2_01", "PRIMARY"): raw if phase == "primary" else "{",
                                  ("DEV2_01", "REPAIR_1"): raw}
                        score = runner.execute(**opts, **flags, mode="run", transport=self.transport(label, script=script))
                        self.assertEqual(score["rows"][0]["terminal_status"], "STRUCTURAL_VALID")
                        directory = opts["output_root"] / label / "artifacts" / "DEV2_01"
                        self.assertEqual(json.loads((directory / f"{phase}_draft.json").read_text()), bad)
                        self.assertEqual(json.loads((directory / f"{phase}_resolved_draft.json").read_text()), resolved)
                        saved = json.loads((directory / "validation.json").read_text())
                        self.assertEqual(saved["validation"]["mention_anchoring"], validation["mention_anchoring"])
                        self.assertEqual(score["anchor_mentions"], True)
                        # A legacy run records both failed attempts. Replay must
                        # sum both even though the anchored primary now passes.
                        runner.execute(**opts, mode="run", transport=self.transport(script={
                            ("DEV2_01", "PRIMARY"): raw, ("DEV2_01", "REPAIR_1"): raw}))
                        source = opts["output_root"] / "P3"
                        before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                        replay = runner.execute(**opts, **flags, mode="revalidate", run_directory=source,
                            transport=Mock(side_effect=AssertionError("offline replay")))
                        self.assertEqual({p: p.read_bytes() for p in before}, before)
                        self.assertTrue(replay["anchor_mentions"])
                        self.assertEqual(replay["totals"]["fixed"], 1)
                        report = validation["mention_anchoring"]
                        for phase_counts in replay["totals"]["by_phase"].values():
                            self.assertEqual(phase_counts["mention_anchoring_report"], report)
                        self.assertEqual(replay["totals"]["mention_anchoring_report"], {
                            kind: {code: count * 2 for code, count in counts.items()}
                            for kind, counts in report.items()})

    def test_host_repair_labels_and_disabled_output_bytes(self):
        for predicates, suffix in ((runner.MENTION_EVIDENCE_PREDICATES, "+ME"),
                                   (("NamedAs", "RefersTo"), "+ME"),
                                   (("RefersTo",), "+ME_R"), (("NamedAs",), "+ME_N")):
            with self.subTest(predicates=predicates):
                self.assertEqual(runner._run_variant("P3", True, True, True, True, True, predicates),
                                 "P3+QR+RB+EN+AM" + suffix)
                self.assertEqual(runner._run_variant("P4R7", True, True, True, True, True, predicates,
                                                    sentence_evidence=True, transfer_bounds=True,
                                                    date_anchor=True),
                                 "P4R7+QR+RB+EN+AM" + suffix + "+SE+TB+DA")
        for option, suffix in (("sentence_evidence", "+SE"), ("transfer_bounds", "+TB"), ("date_anchor", "+DA")):
            self.assertEqual(runner._run_variant("P4R7", False, False, **{option: True}), "P4R7" + suffix)
        for predicates in ((), ("Occurred",)):
            with self.subTest(invalid=predicates), self.assertRaisesRegex(runner.DevelopmentError, "predicates"):
                runner._run_variant("P3", False, False, mention_evidence=True,
                                    mention_evidence_predicates=predicates)

        raw = json.dumps(widened_mention_draft(self.draft))
        snapshots = []
        with self.fixture() as (opts, _, _):
            for flags in ({}, {"mention_evidence": False, "mention_evidence_predicates": ("NamedAs",),
                               "sentence_evidence": False, "transfer_bounds": False, "date_anchor": False}):
                clock = Clock()
                run = {**opts, "output_root": opts["output_root"] / str(len(snapshots)),
                       "clock": clock, "wait": clock.wait}
                fake = self.transport(script={("DEV2_01", "PRIMARY"): raw})
                runner.execute(**run, **flags, mode="run", transport=fake)
                runner.execute(**run, **flags, mode="revalidate", transport=Mock(side_effect=AssertionError))
                root = run["output_root"] / "P3"
                snapshots.append({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})
        self.assertEqual(snapshots[0], snapshots[1])
        for filename in ("score.json", "revalidation.json"):
            for option in (b"mention_evidence", b"sentence_evidence", b"transfer_bounds", b"date_anchor"):
                self.assertNotIn(b'"' + option, snapshots[0][Path(filename)])
        self.assertNotIn(Path("artifacts/DEV2_01/primary_resolved_draft.json"), snapshots[0])

    def test_mention_evidence_applies_after_repairs_in_run_score_and_revalidation(self):
        for phase in ("primary", "repair_1"):
            with self.subTest(phase=phase), self.fixture() as (opts, _, _):
                wide = widened_mention_draft(self.draft)
                flags = {"mention_evidence": True}
                if phase == "repair_1":
                    # QR must restore the quote for AM to locate the mention, then ME narrows it.
                    wide["evidence"][0]["quote"] = "\n".join(wide["evidence"][0]["quote"])
                    wide["mentions"][0]["occurrence"] = 99
                    flags.update(quote_resolution=True, anchor_mentions=True,
                                 mention_evidence_predicates=("RefersTo",))
                label = "P3+QR+AM+ME_R" if phase == "repair_1" else "P3+ME"
                predicates = list(flags.get("mention_evidence_predicates", runner.MENTION_EVIDENCE_PREDICATES))
                raw = json.dumps(wide)
                script = {("DEV2_01", "PRIMARY"): raw if phase == "primary" else "{",
                          ("DEV2_01", "REPAIR_1"): raw}
                fake = self.transport(label, script=script)
                score = runner.execute(**opts, **flags, mode="run", transport=fake)
                self.assertTrue(score["mention_evidence"])
                self.assertEqual(score["mention_evidence_predicates"], predicates)
                self.assertEqual(score["rows"][0]["terminal_status"], "STRUCTURAL_VALID")
                no_provider = Mock(side_effect=AssertionError("host-only"))
                self.assertEqual(runner.execute(**opts, **flags, mode="score", transport=no_provider), score)

                root = opts["output_root"] / label
                saved = root / "artifacts" / "DEV2_01"
                self.assertEqual((saved / f"{phase}_raw.txt").read_text(), raw)
                self.assertEqual(json.loads((saved / f"{phase}_draft.json").read_text()), wide)
                resolved = json.loads((saved / f"{phase}_resolved_draft.json").read_text())
                self.assertEqual([item["quote"] for item in resolved["evidence"]],
                                 ["Mira opened the gate.", "Mira"])
                validation = json.loads((saved / "validation.json").read_text())
                report = validation["validation"]["mention_evidence"]
                self.assertEqual(report["by_predicate"]["RefersTo"]["NARROWED"], 1)
                self.assertEqual((report["evidence_items_added"], report["evidence_items_removed"]), (1, 1))
                self.assertEqual(set(report["by_predicate"]), set(predicates))
                if phase == "repair_1":
                    self.assertEqual(validation["validation"]["mention_anchoring"]["mentions"]
                                     ["ANCHORED_TO_EVIDENCE"], 1)
                    self.assertNotIn("mention_evidence", validation["attempts"][0]["validation"])

                runner.execute(**opts, mode="run", transport=self.transport(script={
                    ("DEV2_01", "PRIMARY"): raw, ("DEV2_01", "REPAIR_1"): raw}))
                source = opts["output_root"] / "P3"
                before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                replay = runner.execute(**opts, **flags, mode="revalidate", run_directory=source,
                                        transport=no_provider)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                self.assertTrue(replay["mention_evidence"])
                self.assertEqual(replay["mention_evidence_predicates"], predicates)
                totals = replay["totals"]
                self.assertEqual(totals["fixed"], int(phase == "repair_1"))
                self.assertEqual(totals["by_phase"]["primary"]["mention_evidence_report"], report)
                if phase == "repair_1":
                    self.assertEqual(totals["by_phase"]["repair_1"]["mention_evidence_report"], report)
                    self.assertEqual(totals["mention_evidence_report"], {
                        "by_predicate": {p: {code: n * 2 for code, n in counts.items()}
                                         for p, counts in report["by_predicate"].items()},
                        "evidence_items_added": 2, "evidence_items_removed": 2,
                    })
                else:
                    self.assertEqual(totals["by_phase"]["repair_1"]["mention_evidence_report"]
                                     ["evidence_items_added"], 0)
                    self.assertEqual(totals["mention_evidence_report"], report)
                no_provider.assert_not_called()

    def test_sentence_evidence_and_transfer_bounds_in_run_score_and_revalidation(self):
        draft, case, gold = transfer_case()
        invalid = {**draft, "unknown_field": True}
        raw = {"primary": json.dumps(invalid), "repair_1": json.dumps(draft)}
        flags = {"quote_resolution": True, "anchor_mentions": True, "mention_evidence": True,
                 "sentence_evidence": True, "transfer_bounds": True, "date_anchor": True}
        label = "P4R7+QR+AM+ME+SE+TB+DA"
        order = ("resolve_quotes", "_anchor_mentions", "narrow_mention_evidence",
                 "widen_to_sentence", "bound_by_transfer", "anchor_dates_to_events")
        repairs = Mock()
        no_provider = Mock(side_effect=AssertionError("offline"))
        with patch.object(self, "context", case.compiler_context), patch.object(self, "gold", gold), \
                self.fixture() as (opts, _, _), ExitStack() as stack:
            opts["variant"] = "P4R7"
            for name in order:
                repair = stack.enter_context(patch.object(runner, name, wraps=getattr(runner, name)))
                repairs.attach_mock(repair, name)
            fake = self.transport(label, script={(case.case_id, phase.upper()): response
                                                for phase, response in raw.items()})
            score = runner.execute(**opts, **flags, mode="run", transport=fake)
            self.assertEqual([call[0] for call in repairs.mock_calls], list(order) * 2)
            self.assertEqual(score["rows"][0]["terminal_status"], "STRUCTURAL_VALID")
            self.assertTrue(score["rows"][0]["repair_used"])
            self.assertTrue(score["sentence_evidence"])
            self.assertTrue(score["transfer_bounds"])
            self.assertTrue(score["date_anchor"])
            repairs.reset_mock()
            self.assertEqual(runner.execute(**opts, **flags, mode="score", transport=no_provider), score)
            self.assertEqual(repairs.mock_calls, [])

            source = opts["output_root"] / label
            saved = source / "artifacts" / case.case_id
            run_validation = json.loads((saved / "validation.json").read_text(encoding="utf-8"))
            for phase, original in (("primary", invalid), ("repair_1", draft)):
                self.assertEqual((saved / f"{phase}_raw.txt").read_text(encoding="utf-8"), raw[phase])
                self.assertEqual(json.loads((saved / f"{phase}_draft.json").read_bytes()), original)
                resolved = json.loads((saved / f"{phase}_resolved_draft.json").read_bytes())
                self.assertTrue(any(e["quote"].endswith("。") for e in resolved["evidence"]))
                self.assertTrue(any(a.get("validity", {}).get("end", {}).get("kind") == "ANCHOR"
                                    for a in resolved["assertions"]))

            before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
            replay = runner.execute(**{**opts, "output_root": source.parent / "replay"}, **flags,
                                    mode="revalidate", run_directory=source, transport=no_provider)
            self.assertEqual([call[0] for call in repairs.mock_calls if call.args[0]], list(order) * 2)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            totals = replay["totals"]
            for name, predicate, code, value in (("sentence_evidence", "Occurred", "WIDENED", 2),
                                                  ("transfer_bounds", "Possesses", "BOTH_SET", 1)):
                self.assertTrue(replay[name])
                self.assertEqual(totals[f"{name}_report"]["by_predicate"][predicate][code], value * 2)
                for attempt in run_validation["attempts"]:
                    report = attempt["validation"][name]
                    phase_report = totals["by_phase"][attempt["phase"]][f"{name}_report"]
                    self.assertEqual(phase_report, report)
                    self.assertEqual(report["by_predicate"][predicate][code], value)
            self.assertEqual(totals["sentence_evidence_report"]["evidence_items_added"], 4)
            self.assertEqual(totals["sentence_evidence_report"]["evidence_items_removed"], 4)
            self.assertTrue(replay["date_anchor"])
            self.assertEqual(totals["date_anchor_report"], runner.anchor_dates_to_events({}, {})[1])
            for attempt in run_validation["attempts"]:
                self.assertEqual(attempt["validation"]["date_anchor"], runner.anchor_dates_to_events({}, {})[1])
            no_provider.assert_not_called()

    def test_rich_blockers_sanitize_values_extract_handles_and_restore_validator(self):
        bad = deepcopy(self.draft)
        bad["assertions"][0]["support"] = {"evidence_sets": [], "derivations": []}
        case = runner.CaseInput("DEV2_01", {}, self.context, ())
        original = runner.compiler.validate_batch_guarded
        _, _, batch, validation = runner.validate_attempt(json.dumps(bad), case, rich_repair_blockers=True)
        self.assertIsNone(batch)
        self.assertIs(runner.compiler.validate_batch_guarded, original)
        rich = [b for b in validation["blockers"] if b["phase"] == "CANONICAL"]
        self.assertIn({"phase": "CANONICAL", "code": "support_path_integrity:NO_SUPPORT_PATH",
                       "path": bad["assertions"][0]["handle"]}, rich)
        self.assertTrue(any(b["code"] == "CANONICAL_CONFORMANCE_FAILURE" for b in validation["blockers"]))
        self.assertNotIn("SECRET_LITERAL", json.dumps(validation))
        batch = {"candidate_records": {"assertions": [{"id": "draftv1-abc-A3"}],
                                        "propositions": [{"id": "draftv1-abc-PROP12"}]}}
        draft = {"assertions": [{"handle": "A3"}], "propositions": [{"handle": "PROP12"}]}
        messages = ["reference_integrity: assertion draftv1-abc-A3 references unknown proposition draftv1-abc-PROP12",
                    "predicate_integrity: proposition PROP12 uses unregistered predicate SECRET_VALUE",
                    "unknown field SECRET_TEXT with 'A3' and 123", "SECRET_WITHOUT_QUOTES"]
        captures = [(batch, {"checks": {"canonical": {"issues": messages}}})]
        blockers = runner._canonical_blockers(draft, captures)
        self.assertEqual([b["path"] for b in blockers], ["A3", "PROP12", "canonical", "canonical"])
        self.assertEqual([b["code"] for b in blockers], ["reference_integrity:ASSERTION_UNKNOWN_PROPOSITION",
                         "predicate_integrity:PREDICATE_UNREGISTERED",
                         "canonical:UNCLASSIFIED_ISSUE", "canonical:UNCLASSIFIED_ISSUE"])
        for failure in ("validator", "validation"):
            with self.subTest(failure=failure):
                target = runner.compiler if failure == "validator" else runner
                name = "validate_batch_guarded" if failure == "validator" else "validate_raw"
                with patch.object(target, name, side_effect=RuntimeError("private")) as replacement:
                    before = runner.compiler.validate_batch_guarded
                    if failure == "validation":
                        with self.assertRaises(RuntimeError):
                            runner.validate_attempt(self.good, case, rich_repair_blockers=True)
                    else:
                        _, _, _, result = runner.validate_attempt(self.good, case, rich_repair_blockers=True)
                        self.assertTrue(any(b["code"] == "CANONICAL_VALIDATOR_EXCEPTION" for b in result["blockers"]))
                    replacement.assert_called()
                    self.assertIs(runner.compiler.validate_batch_guarded, before)
        with self.fixture() as (opts, _, _):
            fake = self.transport("P3+RB", script={("DEV2_01", "PRIMARY"): json.dumps(bad),
                                                   ("DEV2_01", "REPAIR_1"): self.good})
            repair = runner.build_repair_spec
            def check_repair(*args, **kwargs):
                self.assertTrue(any(b["phase"] == "CANONICAL" for b in args[3]["blockers"]))
                spec = repair(*args, **kwargs)
                self.assertIn("NO_SUPPORT_PATH", spec.user_prompt)
                return spec
            with patch.object(runner, "build_repair_spec", side_effect=check_repair):
                runner.execute(**opts, mode="run", transport=fake, rich_repair_blockers=True)

    def test_revalidation_is_offline_preserves_runs_and_reports_transitions(self):
        noisy = deepcopy(self.draft)
        noisy["evidence"][0]["quote"] = "\n".join(noisy["evidence"][0]["quote"])
        ids = ("DEV2_01", "DEV2_02", "DEV2_03", "DEV2_04", "DEV2_05")
        script = {(ids[0], "PRIMARY"): json.dumps(noisy), (ids[0], "REPAIR_1"): "{",
                  (ids[1], "PRIMARY"): self.good, (ids[2], "PRIMARY"): "{", (ids[2], "REPAIR_1"): "{",
                  (ids[3], "PRIMARY"): None, (ids[4], "PRIMARY"): "{", (ids[4], "REPAIR_1"): json.dumps(noisy)}
        with self.fixture(ids) as (opts, _, _):
            runner.execute(**opts, mode="run", transport=self.transport(script=script))
            source = opts["output_root"] / "P3"
            before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
            no_provider = Mock(side_effect=AssertionError("revalidate called provider"))
            replay = runner.execute(**opts, mode="revalidate", run_directory=source,
                                    quote_resolution=True, rich_repair_blockers=True, transport=no_provider)
            no_provider.assert_not_called()
            status_keys = ('cases', 'original_structurally_valid', 'new_structurally_valid',
                           'fixed', 'transitions')
            self.assertEqual({k: replay["totals"][k] for k in status_keys},
                {"cases": 5, "original_structurally_valid": 1,
                "new_structurally_valid": 3, "fixed": 2, "transitions": {
                    "DRAFT_COMPILER_FAILURE->STRUCTURAL_VALID": 1, "JSON_PARSE_FAILURE->STRUCTURAL_VALID": 1,
                    "STRUCTURAL_VALID->STRUCTURAL_VALID": 1,
                    "JSON_PARSE_FAILURE->JSON_PARSE_FAILURE": 1, "TRANSPORT_FAILURE->TRANSPORT_FAILURE": 1}})
            self.assertEqual([a["terminal_status"] for a in replay["rows"][0]["attempts"]],
                             ["STRUCTURAL_VALID", "JSON_PARSE_FAILURE"])
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            destination = opts["output_root"] / "P3+QR+RB" / "revalidation.json"
            self.assertEqual(json.loads(destination.read_text()), replay)
            same = runner.execute(**opts, mode="revalidate", transport=no_provider)
            self.assertEqual(same["totals"]["fixed"], 0)
            with self.assertRaisesRegex(runner.DevelopmentError, "only used"):
                runner.execute(**opts, run_directory=source)
            path = source / "artifacts" / ids[0] / "validation.json"
            saved = json.loads(path.read_text())
            for attempts, error in (([], "Missing saved validation"),
                                    ([{"phase": "../escape"}], "Unknown saved draft"),
                                    ([{"phase": "primary", "validation": {"category": "JSON_PARSE_FAILURE"}}],
                                     "Missing saved draft response")):
                with self.subTest(error=error):
                    (path.parent / "primary_draft.json").unlink(missing_ok=True)
                    (path.parent / "primary_raw.txt").unlink(missing_ok=True)
                    path.write_text(json.dumps({**saved, "attempts": attempts}))
                    with self.assertRaisesRegex(runner.DevelopmentError, error):
                        runner.execute(**opts, mode="revalidate", transport=no_provider)

    def test_revalidation_counts_remaining_blockers_and_resolution_over_all_attempts(self):
        missing, ambiguous, canonical, noisy = (deepcopy(self.draft) for _ in range(4))
        missing['evidence'][0]['quote'] = 'ABSENT_SYNTHETIC_QUOTE'
        # The synthetic source is "Mira opened the gate.": two occurrences of a,
        # but only one mention. Ordered resolution must leave that blocker.
        ambiguous['mentions'][0]['quote'] = 'a'
        ambiguous['mentions'][0].pop('occurrence', None)
        canonical['assertions'][0]['support'] = {'evidence_sets': [], 'derivations': []}
        noisy['evidence'][0]['quote'] = '\n'.join(noisy['evidence'][0]['quote'])
        prepared = runner.prepare_story_extraction_draft_v1_1(self.context)
        cases = [runner.CaseInput(cid, prepared, self.context, ()) for cid in ('DEV2_01', 'DEV2_02')]
        saved_drafts = ((missing, canonical), (noisy, ambiguous))
        for enabled in (False, True):
            with self.subTest(quote_resolution=enabled), tempfile.TemporaryDirectory() as tmp:
                source, destination = Path(tmp) / 'source', Path(tmp) / 'destination'
                expected_reports = {phase: {kind: dict.fromkeys(runner.OUTCOMES, 0)
                    for kind in ('evidence', 'mentions')} for phase in ('primary', 'repair_1')}
                for case, drafts in zip(cases, saved_drafts):
                    directory = source / 'artifacts' / case.case_id
                    directory.mkdir(parents=True)
                    attempts = []
                    for phase, draft in zip(('primary', 'repair_1'), drafts):
                        (directory / f'{phase}_draft.json').write_text(json.dumps(draft), encoding='utf-8')
                        attempts.append({'phase': phase, 'validation': {'category': 'OLD_FAILURE'}})
                        if enabled:
                            _, report = runner.resolve_quotes(draft, prepared)
                            for kind, outcomes in report.items():
                                for code, count in outcomes.items():
                                    expected_reports[phase][kind][code] += count
                    (directory / 'validation.json').write_text(json.dumps({
                        'terminal_status': 'OLD_FAILURE', 'attempts': attempts}), encoding='utf-8')
                before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
                replay = runner.revalidate_cases(cases, source, destination,
                    quote_resolution=enabled, rich_repair_blockers=True)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                self.assertEqual(json.loads((destination / 'revalidation.json').read_text()), replay)
                totals = replay['totals']
                phases = totals['by_phase']
                self.assertEqual(phases['primary']['remaining_blocker_counts'],
                    {'QUOTE:QUOTE_NOT_FOUND': 1 if enabled else 2})
                self.assertEqual(phases['repair_1']['remaining_blocker_counts'], {
                    'CANONICAL:canonical:UNCLASSIFIED_ISSUE': 1,
                    'CANONICAL:support_path_integrity:NO_SUPPORT_PATH': 1,
                    'CANONICAL_COMPILER:CANONICAL_CONFORMANCE_FAILURE': 1,
                    'QUOTE:AMBIGUOUS_QUOTE': 1})
                self.assertEqual(totals['remaining_blocker_counts'], {
                    **phases['primary']['remaining_blocker_counts'],
                    **phases['repair_1']['remaining_blocker_counts']})
                for phase in phases:
                    self.assertEqual(phases[phase]['quote_resolution_report'], expected_reports[phase])
                self.assertEqual(totals['quote_resolution_report'], {
                    kind: {code: sum(expected_reports[phase][kind][code] for phase in phases)
                           for code in runner.OUTCOMES} for kind in ('evidence', 'mentions')})
                # Even when the new primary passes, the saved repair contributes
                # its ambiguous-quote blocker to the phase and overall totals.
                self.assertEqual(replay['rows'][1]['new_terminal_status'],
                                 'STRUCTURAL_VALID' if enabled else 'DRAFT_COMPILER_FAILURE')
                self.assertEqual(replay['rows'][1]['attempts'][1]['terminal_status'],
                                 'DRAFT_COMPILER_FAILURE')

    def test_cli_modes_refusal_and_module_entrypoint(self):
        original = runner.execute
        for dataset in ("DEV1", "DEV2"):
            for mode in ("preflight", "run", "score", "revalidate"):
                fixture = self.dev1_fixture() if dataset == "DEV1" else self.fixture()
                with self.subTest(dataset=dataset, mode=mode), fixture as values:
                    opts = values[0]
                    variant = "P4R3" if dataset == "DEV1" else "P3"
                    opts["variant"] = variant
                    opts["existing_names"] = True
                    opts["anchor_mentions"] = True
                    prompt_root = opts["output_root"].parent / "prompts"
                    prompt_root.mkdir()
                    for name in ("P3", "P4R3"):
                        (prompt_root / f"story_extraction_draft_{name.lower()}_system_v1_1.txt").write_text(
                            f"SYNTHETIC {name} PREAMBLE", encoding="utf-8")
                    fake = self.transport(variant + "+EN+AM", dataset=dataset,
                                          script={(cid, "PRIMARY"): self.good for cid in opts["cases"]})
                    argv = ["--variant", variant, "--output-root", str(opts["output_root"]),
                            "--cases", ",".join(opts["cases"]), "--mode", mode, "--existing-names", "--anchor-mentions"]
                    if dataset == "DEV1":
                        argv += ["--dataset", dataset]
                    if mode == "revalidate":
                        argv += ["--mention-evidence", "--mention-evidence-predicates", "NamedAs, RefersTo",
                                 "--sentence-evidence", "--transfer-bounds"]
                    for key in ("dev1_package", "dev1_ingestion_manifest", "dev1_source_root",
                                "dev2_input", "dev2_gold"):
                        if key in opts:
                            argv += ["--" + key.replace("_", "-"), str(opts[key])]
                    returned = []
                    def execute_cli(**kwargs):
                        result = original(**{**opts, **kwargs}, transport=fake)
                        returned.append(result)
                        return result
                    output = io.StringIO()
                    with patch.object(runner, "PROMPT_ROOT", prompt_root):
                        if mode in ("score", "revalidate"):
                            original(**opts, mode="run", transport=fake)
                        if mode == "revalidate":
                            source = opts["output_root"] / ("DEV1" if dataset == "DEV1" else "") / (variant + "+EN+AM")
                            argv += ["--quote-resolution", "--rich-repair-blockers", "--run-directory", str(source)]
                        with patch.object(runner, "execute", side_effect=execute_cli), redirect_stdout(output):
                            self.assertEqual(runner.main(argv), 0)
                        self.assertIsInstance(json.loads(output.getvalue()), dict)
                        if mode == 'revalidate':
                            self.assertEqual(json.loads(output.getvalue()), returned[-1]['totals'])
                            self.assertIn('remaining_blocker_counts', returned[-1]['totals'])
                            self.assertIn('quote_resolution_report', returned[-1]['totals'])
                            self.assertIn('mention_anchoring_report', returned[-1]['totals'])
                            self.assertIn('mention_evidence_report', returned[-1]['totals'])
                            self.assertEqual(returned[-1]['mention_evidence_predicates'], ['RefersTo', 'NamedAs'])
                            self.assertIn('sentence_evidence_report', returned[-1]['totals'])
                            self.assertIn('transfer_bounds_report', returned[-1]['totals'])
                            self.assertEqual(set(returned[-1]['totals']['by_phase']), {'primary', 'repair_1'})
                        with patch.object(runner, "execute", side_effect=runner.DevelopmentError("private")), redirect_stdout(output):
                            self.assertEqual(runner.main(argv), 2)
                        self.assertIn("M4_P4_DEV_STOPPED: DevelopmentError", output.getvalue())
        with patch("sys.argv", [runner.__name__]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_module(runner.__name__, run_name="__main__")
            self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
