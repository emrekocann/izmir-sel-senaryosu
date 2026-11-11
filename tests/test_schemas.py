import pytest
from pydantic import ValidationError
from schemas import QuakeCreateRequest

def test_quake_schema_validation_error():
    """Eksik veya hatalı veri geldiğinde Pydantic'in tepkisini ölçer."""
    # Hatalı veri: Enlem (lat) 90'dan büyük olamaz
    invalid_data = {
        "buyukluk": 5.5,
        "yer": "Buca",
        "lat": 120.0, 
        "lon": 27.0
    }
    with pytest.raises(ValidationError) as exc_info:
        QuakeCreateRequest(**invalid_data)
    
    assert "lat" in str(exc_info.value)
    print("\n[Graceful Failure] Sistem hatalı enlem değerini başarıyla reddetti.")