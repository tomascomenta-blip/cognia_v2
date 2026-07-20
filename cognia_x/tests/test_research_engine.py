"""
test_research_engine.py — regresiones del Investigation Engine (cognia_x/research/).

Cada test es una aserción REAL contra una compuerta enforzada por la directiva v2: jerarquía de
evidencia, falsabilidad + DoD, analogía de 7 etapas, taxonomía de techos, y verificación de no-pérdida.
"""
import os
import tempfile
import unittest

from cognia_x.research.schema import (
    Source, Decision, Hypothesis, AnalogyRecord, CeilingRecord, ScalabilityNote,
    to_dict, from_dict,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry, PrematureVerdictError
from cognia_x.research.analogy import extract_principles, IncompleteAnalogyError
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord, count_lines


class TmpMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='research_test_')

    def store(self, name):
        return os.path.join(self.tmp, name)


class TestEvidenceLedger(TmpMixin):
    def test_rejects_opinion_only_important_decision(self):
        led = EvidenceLedger(self.store('ledger_opinion'))
        # única fuente: tier 6 + una tier 1 NO obtenida -> ambas grado-opinión.
        dec = Decision(
            id='D1', statement='optimizar X', rationale='porque sí',
            sources=[
                to_dict(Source(tier=6, ref='blog.com', claim='dicen que sí')),
                to_dict(Source(tier=1, ref='arXiv:0000', claim='paper', obtained=False)),
            ],
            important=True,
        )
        with self.assertRaises(OpinionOnlyError):
            led.record_decision(dec)

    def test_accepts_tier1_paper(self):
        led = EvidenceLedger(self.store('ledger_paper'))
        dec = Decision(
            id='D2', statement='usar método Y', rationale='paper lo prueba',
            sources=[to_dict(Source(tier=1, ref='arXiv:1234.5678', claim='Y mejora Z', obtained=True))],
            important=True,
        )
        out = led.record_decision(dec)
        self.assertEqual(out.id, 'D2')
        self.assertEqual(count_lines(led.record.store_path('decisions')), 1)

    def test_accepts_tier5_own_datum(self):
        led = EvidenceLedger(self.store('ledger_own'))
        dec = Decision(
            id='D3', statement='congelar tronco', rationale='exp propio',
            sources=[to_dict(Source(tier=5, ref='exp008', claim='recall sube', obtained=True))],
            important=True,
        )
        out = led.record_decision(dec)
        self.assertEqual(out.id, 'D3')

    def test_non_important_passes_flagged(self):
        led = EvidenceLedger(self.store('ledger_flag'))
        dec = Decision(
            id='D4', statement='probar tipografía', rationale='cosmético',
            sources=[to_dict(Source(tier=6, ref='blog', claim='se ve lindo'))],
            important=False,
        )
        # no debe lanzar; pasa pero flagged.
        led.record_decision(dec)
        self.assertEqual(count_lines(led.record.store_path('decisions')), 1)


class TestHypotheses(TmpMixin):
    def _full_hyp(self):
        return Hypothesis(
            id='H1', statement='congelar el tronco preserva recall',
            prediction='recall@10 sube >5pts vs baseline',
            evidence_for=['exp008: +7pts'],
            evidence_against=['exp005: sin efecto en tareas cortas'],
            adversarial_verdict='el crítico no halló confusor; el efecto persiste con otra semilla',
            experiment_ref='exp008',
        )

    def test_mark_supported_raises_without_evidence_against(self):
        reg = HypothesisRegistry(self.store('hyp_against'))
        h = self._full_hyp()
        h.evidence_against = []
        reg.add(h)
        with self.assertRaises(PrematureVerdictError):
            reg.mark_supported('H1')

    def test_mark_supported_raises_without_experiment(self):
        reg = HypothesisRegistry(self.store('hyp_exp'))
        h = self._full_hyp()
        h.experiment_ref = ''
        reg.add(h)
        with self.assertRaises(PrematureVerdictError):
            reg.mark_supported('H1')

    def test_mark_supported_succeeds_full_dod(self):
        reg = HypothesisRegistry(self.store('hyp_ok'))
        reg.add(self._full_hyp())
        out = reg.mark_supported('H1')
        self.assertEqual(out.status, 'apoyada')
        self.assertEqual(reg.get('H1').status, 'apoyada')

    def test_mark_refuted_succeeds_full_dod(self):
        reg = HypothesisRegistry(self.store('hyp_ref'))
        reg.add(self._full_hyp())
        out = reg.mark_refuted('H1')
        self.assertEqual(out.status, 'refutada')


class TestAnalogy(TmpMixin):
    def test_raises_with_few_solutions(self):
        rec = AnalogyRecord(
            problem='memoria se desborda', everyday='biblioteca llena',
            solutions=['archivar lo viejo'],
        )
        with self.assertRaises(IncompleteAnalogyError):
            extract_principles(rec)

    def test_raises_without_everyday(self):
        rec = AnalogyRecord(
            problem='memoria se desborda', everyday='',
            solutions=['a', 'b', 'c'],
        )
        with self.assertRaises(IncompleteAnalogyError):
            extract_principles(rec)

    def test_succeeds_with_three_solutions(self):
        rec = AnalogyRecord(
            problem='memoria se desborda', everyday='biblioteca llena',
            solutions=['archivar lo viejo', 'comprimir resúmenes', 'índice por tema'],
        )
        principles = extract_principles(rec)
        self.assertEqual(len(principles), 3)
        self.assertEqual(rec.principles, principles)


class TestCeiling(TmpMixin):
    def test_rejects_bad_kind(self):
        ct = CeilingTracker(self.store('ceil_kind'))
        rec = CeilingRecord(
            subsystem='attention', known_limit='O(n^2)',
            blockers=[{'text': 'softmax full', 'kind': 'cuantico'}],
            real_or_assumed='real',
        )
        with self.assertRaises(ValueError):
            ct.add(rec)

    def test_rejects_bad_real_or_assumed(self):
        ct = CeilingTracker(self.store('ceil_roa'))
        rec = CeilingRecord(
            subsystem='attention', known_limit='O(n^2)',
            blockers=[{'text': 'x', 'kind': 'diseno'}],
            real_or_assumed='quizas',
        )
        with self.assertRaises(ValueError):
            ct.add(rec)

    def test_rejects_empty_blockers(self):
        # §5: un techo debe clasificar qué lo impide; blockers=[] no clasifica nada -> ValueError.
        ct = CeilingTracker(self.store('ceil_empty'))
        rec = CeilingRecord(
            subsystem='sub2', known_limit='lim2', blockers=[], real_or_assumed='asumido',
        )
        with self.assertRaises(ValueError):
            ct.add(rec)

    def test_assumed_limits_returns_only_asumido(self):
        ct = CeilingTracker(self.store('ceil_assumed'))
        ct.add(CeilingRecord(
            subsystem='ctx', known_limit='2k tokens',
            blockers=[{'text': 'cap hardcoded', 'kind': 'historico'}],
            real_or_assumed='asumido', evidence=['constante en model_constants'],
        ))
        ct.add(CeilingRecord(
            subsystem='float', known_limit='precisión IEEE754',
            blockers=[{'text': 'mantisa finita', 'kind': 'fisico'}],
            real_or_assumed='real', evidence=['IEEE 754'],
        ))
        assumed = ct.assumed_limits()
        self.assertEqual(len(assumed), 1)
        self.assertEqual(assumed[0].subsystem, 'ctx')


class TestPermanentRecord(TmpMixin):
    def test_verify_ok_after_normal_adds(self):
        led = EvidenceLedger(self.tmp)
        led.add_source(Source(tier=1, ref='arXiv:1', claim='c1'))
        led.add_source(Source(tier=5, ref='exp001', claim='c2'))
        led.record_decision(Decision(
            id='D1', statement='s', rationale='r',
            sources=[to_dict(Source(tier=1, ref='arXiv:1', claim='c1', obtained=True))],
        ))
        res = PermanentRecord(self.tmp).verify_no_loss()
        self.assertTrue(res['ok'], res)

    def test_verify_fail_after_truncation(self):
        led = EvidenceLedger(self.tmp)
        led.add_source(Source(tier=1, ref='arXiv:1', claim='c1'))
        led.add_source(Source(tier=1, ref='arXiv:2', claim='c2'))
        # simular pérdida: borrar una línea del store de sources.
        sp = led.record.store_path('sources')
        with open(sp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(sp, 'w', encoding='utf-8') as f:
            f.writelines(lines[:-1])  # elimina el último registro
        res = PermanentRecord(self.tmp).verify_no_loss()
        self.assertFalse(res['ok'], res)
        srcdetail = [d for d in res['details'] if d['store'] == 'sources'][0]
        self.assertEqual(srcdetail['journaled'], 2)
        self.assertEqual(srcdetail['live'], 1)

    def test_verify_fail_after_delete_plus_unrelated_add(self):
        # REGRESIÓN (finding medium): borrar un registro journaleado y añadir OTRO no relacionado deja
        # el conteo igual (live==journaled) pero pierde conocimiento. El check por contenido lo detecta.
        rec = PermanentRecord(self.tmp)
        rec.journaled_append('sources', {'ref': 'a', 'claim': '1'}, key='a')
        rec.journaled_append('sources', {'ref': 'b', 'claim': '2'}, key='b')
        rec.journaled_append('sources', {'ref': 'c', 'claim': '3'}, key='c')
        sp = rec.store_path('sources')
        with open(sp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # borra el último registro journaleado y mete uno NO journaleado (conteo se mantiene en 3).
        with open(sp, 'w', encoding='utf-8') as f:
            f.writelines(lines[:-1])
            f.write('{"ref": "zz", "claim": "no journaleado"}\n')
        res = PermanentRecord(self.tmp).verify_no_loss()
        self.assertFalse(res['ok'], res)
        srcdetail = [d for d in res['details'] if d['store'] == 'sources'][0]
        self.assertEqual(srcdetail['live'], 3)        # conteo intacto
        self.assertEqual(srcdetail['journaled'], 3)
        self.assertEqual(srcdetail['missing'], 1)     # pero falta un hash journaleado

    def test_verify_ok_with_versioned_hypothesis_states(self):
        # Append-only en registros versionados: mark_supported añade una línea de estado nueva (mismo id,
        # contenido distinto). Ambos estados están journaleados; verify debe seguir OK (nada se perdió).
        reg = HypothesisRegistry(self.tmp)
        reg.add(Hypothesis(
            id='H1', statement='s', prediction='p sube',
            evidence_for=['e+'], evidence_against=['e-'],
            adversarial_verdict='ok', experiment_ref='exp1',
        ))
        reg.mark_supported('H1')
        res = PermanentRecord(self.tmp).verify_no_loss()
        self.assertTrue(res['ok'], res)


class TestScalabilityNoteSerializes(TmpMixin):
    def test_roundtrip(self):
        note = ScalabilityNote(
            component='ledger', time_complexity='O(1) append',
            space_complexity='O(1)', cpu_behavior='I/O-bound',
            multidevice='JSONL portable', distribution='merge append-only',
        )
        d = to_dict(note)
        back = from_dict(ScalabilityNote, d)
        self.assertEqual(back.component, 'ledger')


if __name__ == '__main__':
    unittest.main()
