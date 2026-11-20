import unittest

from incidents.priority_scorer import PriorityScorer


class TestPriorityScorer(unittest.TestCase):

    def setUp(self):
        self.scorer = PriorityScorer()

    def test_calculate_score(self):

        score = self.scorer.calculate_score(
            severity=90,
            breadth=70,
            duration=80,
            criticality=100,
            confidence=90
        )

        self.assertEqual(score, 85.5)

    def test_p1_priority(self):
        self.assertEqual(
            self.scorer.get_priority(85),
            "P1"
        )

    def test_p2_priority(self):
        self.assertEqual(
            self.scorer.get_priority(65),
            "P2"
        )

    def test_p3_priority(self):
        self.assertEqual(
            self.scorer.get_priority(45),
            "P3"
        )

    def test_p4_priority(self):
        self.assertEqual(
            self.scorer.get_priority(20),
            "P4"
        )

    def test_priority_boundary_80(self):
        self.assertEqual(
            self.scorer.get_priority(80),
            "P1"
        )

    def test_priority_boundary_60(self):
        self.assertEqual(
            self.scorer.get_priority(60),
            "P2"
        )

    def test_priority_boundary_40(self):
        self.assertEqual(
            self.scorer.get_priority(40),
            "P3"
        )

    def test_priority_boundary_zero(self):
        self.assertEqual(
            self.scorer.get_priority(0),
            "P4"
        )

    def test_priority_boundary_100(self):
        self.assertEqual(
            self.scorer.get_priority(100),
            "P1"
        )

    def test_score_incident(self):

        result = self.scorer.score_incident(
            severity=90,
            breadth=70,
            duration=80,
            criticality=100,
            confidence=90
        )

        self.assertEqual(
            result,
            {
                "priority_score": 85.5,
                "priority": "P1"
            }
        )

    def test_invalid_negative_score(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity=-1,
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_invalid_score_above_100(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity=101,
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_invalid_string_score(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity="high",
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_boolean_score_rejected(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity=True,
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_nan_score_rejected(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity=float("nan"),
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_infinite_score_rejected(self):

        with self.assertRaises(ValueError):

            self.scorer.calculate_score(
                severity=float("inf"),
                breadth=50,
                duration=50,
                criticality=50,
                confidence=50
            )

    def test_invalid_priority_score(self):

        with self.assertRaises(ValueError):
            self.scorer.get_priority(-10)

        with self.assertRaises(ValueError):
            self.scorer.get_priority(110)

    def test_all_zero_scores(self):

        result = self.scorer.score_incident(
            severity=0,
            breadth=0,
            duration=0,
            criticality=0,
            confidence=0
        )

        self.assertEqual(
            result["priority_score"],
            0
        )

        self.assertEqual(
            result["priority"],
            "P4"
        )

    def test_all_maximum_scores(self):

        result = self.scorer.score_incident(
            severity=100,
            breadth=100,
            duration=100,
            criticality=100,
            confidence=100
        )

        self.assertEqual(
            result["priority_score"],
            100
        )

        self.assertEqual(
            result["priority"],
            "P1"
        )


if __name__ == "__main__":
    unittest.main()