import math
import pytest
from app.ai.shopping_copilot.semantic import vector_literal


def test_embedding_validation_rejects_wrong_dimensions_nonfinite_and_zero():
    for values in ([1.0], [math.nan, 1.0], [math.inf, 1.0], [0.0, 0.0]):
        with pytest.raises(ValueError):
            vector_literal(values, 2)
    assert vector_literal([1.0, 0.0], 2) == "[1.0,0.0]"
