from src.aiops.anomaly import AnomalyDetector


def test_detect_normal_value():
    detector = AnomalyDetector(threshold=3.0)

    baseline = {
        "count": 10,
        "mean": 50,
        "stddev": 5,
    }

    result = detector.detect(55, baseline)

    assert result["is_anomaly"] is False
    assert result["severity"] == "normal"
    assert result["z_score"] == 1.0


def test_detect_critical_anomaly():
    detector = AnomalyDetector(threshold=3.0)

    baseline = {
        "count": 10,
        "mean": 50,
        "stddev": 5,
    }

    result = detector.detect(80, baseline)

    assert result["is_anomaly"] is True
    assert result["severity"] == "critical"
    assert result["z_score"] == 6.0


def test_insufficient_baseline():
    detector = AnomalyDetector()

    baseline = {
        "count": 1,
        "mean": 50,
        "stddev": 0,
    }

    result = detector.detect(90, baseline)

    assert result["is_anomaly"] is False
    assert result["severity"] == "normal"
    assert result["z_score"] == 0.0


def test_medium_anomaly():
    detector = AnomalyDetector(threshold=3.0)

    baseline = {
        "count": 10,
        "mean": 50,
        "stddev": 5,
    }

    result = detector.detect(67.5, baseline)

    assert result["is_anomaly"] is True
    assert result["severity"] == "medium"
    assert result["z_score"] == 3.5