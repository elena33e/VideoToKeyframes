"""Analiza identității rămâne propunere și își verifică sursele."""

import unittest

from pydantic import ValidationError
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS

import tests.session_context.identity.test_session_identity as fixtures

from session_context.characteristics.comparison import (
    characteristics_for_occurrence,
)
from session_context.identity.analysis import (
    IdentityAnalysisProposal,
    check_identity_analysis_proposal,
)


EX = Namespace("https://example.test/identity-analysis#")
NOTE = (
    "In this test ontology, identity requires continuity of "
    "the same physical body and permits a surface colour change."
)


class IdentityAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SessionIdentityTest()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.context = self.fixture.context
        self.a = self.fixture.a
        self.b = self.fixture.b
        self.c = self.fixture.c

        self.ontology = Graph()
        self.ontology.add((EX.Item, RDF.type, OWL.Class))
        self.ontology.add((
            EX.Item, RDFS.comment, Literal(NOTE, lang="en")
        ))

    def source_uncertain(self, occurrence):
        marker = self.context.observations.value(
            occurrence, fixtures.CTX.uncertain, any=False
        )
        return marker != Literal(False)

    def condition(self, occurrence=None, **changes):
        occurrence = self.a if occurrence is None else occurrence
        data = {
            "description": "Continuitatea aceluiași corp fizic.",
            "scope_description": (
                "Obiectele clasei din ontologia sintetică de test."
            ),
            "origin": "ontology_text",
            "justification": (
                "Condiție propusă pornind de la textul citat."
            ),
            "ontology_evidence": [{
                "subject_iri": str(EX.Item),
                "predicate_iri": str(RDFS.comment),
                "quotation": (
                    "identity requires continuity of "
                    "the same physical body"
                ),
                "language": "en",
            }],
            "relevant_observation_iris": [str(occurrence)],
            "required_evidence": [
                "Dovezi care leagă aparițiile de același corp fizic."
            ],
            "uncertain": self.source_uncertain(occurrence),
        }
        data.update(changes)
        return data

    def analysis(self, occurrence=None, **changes):
        occurrence = self.a if occurrence is None else occurrence
        data = {
            "occurrence_iri": str(occurrence),
            "entity_kind": "obiect fizic",
            "entity_kind_reason": (
                "Interpretare propusă pentru scenariul de test."
            ),
            "tracking_unit": "Obiectul individual considerat ca întreg.",
            "granularity": (
                "Un obiect, distinct de material și de stările sale."
            ),
            "ontology_reference_iris": [str(EX.Item)],
            "identity_conditions": [self.condition(occurrence)],
            "compatible_changes": [],
            "identity_boundaries": [],
            "unresolved_questions": [
                "Continuitatea între cadre nu este încă demonstrată."
            ],
            "uncertain": self.source_uncertain(occurrence),
        }
        data.update(changes)
        return data

    def proposal(self, *appearances):
        return IdentityAnalysisProposal.model_validate({
            "appearances": list(appearances),
        })

    def check(self, proposal, expected=None):
        return check_identity_analysis_proposal(
            proposal,
            context=self.context,
            expected_occurrences=(
                (self.a,) if expected is None else expected
            ),
            ontology=self.ontology,
        )

    def test_valid_analysis_preserves_status_and_graphs(self):
        proposal = self.proposal(self.analysis())
        before = set(self.context.dataset.quads(
            (None, None, None, None)
        ))

        result = self.check(proposal)

        self.assertEqual("proposal", result.status)
        self.assertEqual(proposal, result)
        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )
        self.assertEqual(0, len(self.context.identities))

    def test_missing_criteria_can_remain_unresolved(self):
        proposal = self.proposal(self.analysis(
            entity_kind=None,
            identity_conditions=[],
            unresolved_questions=[
                "Natura entității și criteriul nu sunt stabilite."
            ],
            uncertain=True,
        ))

        result = self.check(proposal)

        self.assertEqual(
            (), result.appearances[0].identity_conditions
        )
        self.assertTrue(result.appearances[0].uncertain)

    def test_unresolved_analysis_requires_explanation_and_uncertainty(self):
        invalid = (
            {
                "entity_kind": None,
                "uncertain": False,
            },
            {
                "identity_conditions": [],
                "unresolved_questions": [],
            },
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    self.proposal(self.analysis(**changes))

    def test_ontology_origin_requires_a_quote_and_hypothesis_is_uncertain(self):
        invalid = (
            self.condition(ontology_evidence=[]),
            self.condition(
                origin="model_hypothesis",
                ontology_evidence=[],
                uncertain=False,
            ),
            self.condition(required_evidence=[]),
        )
        for condition in invalid:
            with self.subTest(condition=condition):
                with self.assertRaises(ValidationError):
                    self.proposal(self.analysis(
                        identity_conditions=[condition]
                    ))

        hypothesis = self.condition(
            origin="model_hypothesis",
            ontology_evidence=[],
            uncertain=True,
        )
        self.check(self.proposal(self.analysis(
            identity_conditions=[hypothesis]
        )))

    def test_invented_or_misattributed_quote_is_rejected(self):
        invalid = (
            {"quotation": "Un criteriu care nu apare în sursă."},
            {"subject_iri": str(EX.Missing)},
            {"language": "ro"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                condition = self.condition()
                condition["ontology_evidence"][0].update(changes)
                proposal = self.proposal(self.analysis(
                    identity_conditions=[condition]
                ))

                with self.assertRaises(ValueError):
                    self.check(proposal)

    def test_all_condition_groups_have_their_sources_checked(self):
        for field in (
            "identity_conditions",
            "compatible_changes",
            "identity_boundaries",
        ):
            with self.subTest(field=field):
                condition = self.condition()
                condition["ontology_evidence"][0][
                    "quotation"
                ] = "Citat inventat."
                proposal = self.proposal(self.analysis(
                    **{field: [condition]}
                ))

                with self.assertRaises(ValueError):
                    self.check(proposal)

    def test_missing_duplicate_or_incomplete_coverage_is_rejected(self):
        row = self.analysis()
        cases = (
            ([], (self.a,)),
            ([row, row], (self.a,)),
            ([row], (self.a, self.b)),
            ([row], (self.a, self.a)),
        )
        for rows, expected in cases:
            with self.subTest(rows=rows, expected=expected):
                with self.assertRaises(ValueError):
                    self.check(
                        self.proposal(*rows),
                        expected=expected,
                    )

    def test_foreign_ontology_or_observation_reference_is_rejected(self):
        invalid = (
            self.analysis(
                ontology_reference_iris=[str(EX.Missing)]
            ),
            self.analysis(identity_conditions=[
                self.condition(
                    relevant_observation_iris=["urn:test:foreign"]
                )
            ]),
        )
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    self.check(self.proposal(row))

    def test_uncertain_entity_cannot_become_certain(self):
        # Pregătim explicit o entitate observată ca incertă.
        self.context.observations.set((
            self.c,
            fixtures.CTX.uncertain,
            Literal(True),
        ))

        proposal = self.proposal(self.analysis(
            self.c, uncertain=False
        ))

        with self.assertRaises(ValueError):
            self.check(proposal, expected=(self.c,))

    def test_uncertain_characteristic_does_not_make_entity_analysis_uncertain(self):
        characteristic = characteristics_for_occurrence(
            self.context, self.c
        )[0]
        self.assertTrue(characteristic.uncertain)
        self.assertFalse(self.source_uncertain(self.c))

        result = self.check(
            self.proposal(self.analysis(self.c)),
            expected=(self.c,),
        )

        self.assertFalse(result.appearances[0].uncertain)

    def test_uncertain_characteristic_keeps_condition_uncertain(self):
        source = characteristics_for_occurrence(
            self.context, self.c
        )[0]
        condition = self.condition(
            relevant_observation_iris=[str(source.iri)],
            uncertain=False,
        )

        with self.assertRaises(ValueError):
            self.check(self.proposal(self.analysis(
                identity_conditions=[condition]
            )))

        condition["uncertain"] = True
        self.check(self.proposal(self.analysis(
            identity_conditions=[condition]
        )))

    def test_accepted_status_is_not_part_of_the_contract(self):
        with self.assertRaises(ValidationError):
            IdentityAnalysisProposal.model_validate({
                "status": "accepted",
                "appearances": [],
            })


if __name__ == "__main__":
    unittest.main()