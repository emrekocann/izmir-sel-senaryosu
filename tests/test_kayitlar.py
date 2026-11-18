import pytest
from pydantic import ValidationError
from afet.veritabani.kayitlar import DepremKaydi

def test_deprem_kaydi_gecersiz_enlemi_reddeder():
    """Eksik veya hatalı veri geldiğinde Pydantic'in tepkisini ölçer."""
    # Hatalı veri: Enlem (lat) 90'dan büyük olamaz
    invalid_data = {
        "buyukluk": 5.5,
        "yer": "Buca",
        "lat": 120.0, 
        "lon": 27.0
    }
    with pytest.raises(ValidationError) as exc_info:
        DepremKaydi(**invalid_data)
    
    assert "lat" in str(exc_info.value)
    print("\n[Graceful Failure] Sistem hatalı enlem değerini başarıyla reddetti.")