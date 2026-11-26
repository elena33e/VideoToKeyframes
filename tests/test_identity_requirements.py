"""Domeniul criteriilor este explicit, fără metadate redundante."""

import unittest

from pydantic import ValidationError

import test_frame_candidates as fixtures
from session_context.identity_criteria import (
    IdentityCriteria,
    IdentityRequirements,
)
from session_context.matching import assess_frame_identity
from session_context.type_alignment import SessionTypeMapper
from test_ontology_alignment import NS, make_source


class IdentityRequirementsTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.FrameCandidatesTest()
        self.base.setUp()

        self.fields = {
            "identity_scope_iri": "urn:test:PhysicalIndividual",
            "applicable_class_iris": (
                NS + "A",
                NS + "B",
            ),
            "justification": (
                "Criteriile urmăresc individul fizic "
                "în clasificările declarate."
            ),
        }

    def make_criteria(self, **changes):
        fields = self.base.criteria.model_dump()
        fields["identity_requirements"] = {
            **self.fields,
            **changes,
        }

        return IdentityCriteria.model_validate(fields)

    def assess(self, criteria):
        context = self.base.context
        before = set(
            context.dataset.quads((None, None, None, None))
        )

        results = assess_frame_identity(
            context,
            "frame-1",
            "frame-2",
            mapper=self.base.mapper,
            criteria_by_occurrence={
                self.base.b: criteria,
            },
            language="ro",
        )

        self.assertEqual(
            before,
            set(context.dataset.quads(
                (None, None, None, None)
            )),
        )
        self.assertEqual(1, len(results))

        return results[0]

    def test_existing_criteria_keep_scope_unconfigured(self):
        criteria = self.base.criteria

        self.assertIsNone(criteria.identity_requirements)

        result = self.assess(criteria)

        self.assertIn(
            "criteria_scope_not_configured",
            result.reasons,
        )
        self.assertEqual("unresolved", result.action)

    def test_matching_proposed_types_do_not_establish_identity(self):
        result = self.assess(self.make_criteria())

        self.assertIn(
            "criteria_scope_proposed",
            result.reasons,
        )
        self.assertIn(
            "identity_evidence_required",
            result.reasons,
        )
        self.assertEqual("unresolved", result.action)

    def test_outside_scope_proposal_is_explained_without_exclusion(self):
        result = self.assess(self.make_criteria(
            applicable_class_iris=(NS + "A",),
        ))

        self.assertIn(
            "criteria_scope_not_supported",
            result.reasons,
        )
        self.assertEqual(1, len(result.selection.candidates))
        self.assertEqual(
            (),
            result.selection.excluded_candidates,
        )

    def test_ambiguous_types_leave_scope_unresolved(self):
        self.base.mapper = SessionTypeMapper(make_source("""
            ex:A a owl:Class ;
                rdfs:label "element"@ro .
            ex:Other a owl:Class ;
                rdfs:label "element"@ro .
            ex:B a owl:Class ;
                rdfs:label "element finisat"@ro .
        """))

        result = self.assess(self.make_criteria())

        self.assertIn(
            "criteria_scope_unresolved",
            result.reasons,
        )
        self.assertNotIn(
            "criteria_scope_proposed",
            result.reasons,
        )
        self.assertEqual(1, len(result.selection.candidates))

    def test_invalid_requirements_are_rejected(self):
        invalid = (
            {"applicable_class_iris": ()},
            {
                "applicable_class_iris": (
                    NS + "A",
                    NS + "A",
                ),
            },
            {"identity_scope_iri": "relative-name"},
            {"applicable_class_iris": ("relative-name",)},
            {"justification": "   "},
            {"ontology_source": "obsolete-field.ttl"},
            {"required_evidence_iris": ("urn:test:Evidence",)},
        )

        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    IdentityRequirements(
                        **{**self.fields, **changes}
                    )

    def test_criteria_round_trip_preserves_scope(self):
        criteria = self.make_criteria()

        restored = IdentityCriteria.model_validate_json(
            criteria.model_dump_json()
        )

        self.assertEqual(criteria, restored)
        self.assertEqual(
            self.fields,
            restored.identity_requirements.model_dump(),
        )


if __name__ == "__main__":
    unittest.main()