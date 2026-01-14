"""Configuration for Vietlott SMS Predictor."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal


# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class LotteryConfig:
    """Configuration for a lottery product."""

    name: str
    min_val: int
    max_val: int
    numbers_to_pick: int
    data_file: Path
    url: str
    sms_code: str
    result_page_url: str = ""
    has_bonus: bool = False
    product_type: str = "power"  # "power" for 645/655, "max3d" for Max 3D/Pro

    def __post_init__(self):
        if isinstance(self.data_file, str):
            self.data_file = Path(self.data_file)


@dataclass
class PredictorConfig:
    """Configuration for the predictor."""

    # Strategy weights
    frequency_weight: float = 0.25
    pattern_weight: float = 0.25
    lstm_weight: float = 0.50

    # Frequency strategy params
    freq_lookback_days: int = 365
    freq_hot_weight: float = 0.6
    freq_cold_weight: float = 0.4

    # Pattern strategy params
    pattern_lookback_days: int = 180

    # LSTM params
    lstm_sequence_length: int = 30
    lstm_hidden_size: int = 128
    lstm_num_layers: int = 2
    lstm_dropout: float = 0.2
    lstm_epochs: int = 100
    lstm_batch_size: int = 32
    lstm_learning_rate: float = 0.001

    # Output
    num_tickets: int = 6

    # GPU
    use_gpu: bool = True


# Product configurations
POWER_655_CONFIG = LotteryConfig(
    name="power_655",
    min_val=1,
    max_val=55,
    numbers_to_pick=6,
    data_file=DATA_DIR / "power655.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game655CompareWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="655",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/655",
    has_bonus=True,
)

POWER_645_CONFIG = LotteryConfig(
    name="power_645",
    min_val=1,
    max_val=45,
    numbers_to_pick=6,
    data_file=DATA_DIR / "power645.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game645CompareWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="645",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/645",
    has_bonus=False,
)

MAX3D_CONFIG = LotteryConfig(
    name="max_3d",
    min_val=0,
    max_val=999,
    numbers_to_pick=20,  # Total 3D numbers per draw (varies by prize)
    data_file=DATA_DIR / "max3d.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="3D",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/max-3d",
    has_bonus=False,
    product_type="max3d",
)

MAX3D_PRO_CONFIG = LotteryConfig(
    name="max_3d_pro",
    min_val=0,
    max_val=999,
    numbers_to_pick=20,
    data_file=DATA_DIR / "max3d_pro.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DProResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="3DPRO",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/max-3dpro",
    has_bonus=False,
    product_type="max3d",
)

LOTTO_535_CONFIG = LotteryConfig(
    name="lotto_535",
    min_val=1,
    max_val=35,
    numbers_to_pick=5,
    data_file=DATA_DIR / "lotto535.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game535ResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="535",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535",
    has_bonus=True,
    product_type="power",
)

KENO_CONFIG = LotteryConfig(
    name="keno",
    min_val=1,
    max_val=80,
    numbers_to_pick=20,
    data_file=DATA_DIR / "keno.jsonl",
    url="https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameKenoResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
    sms_code="KENO",
    result_page_url="https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/keno",
    has_bonus=False,
    product_type="keno",
)

PRODUCTS = {
    "655": POWER_655_CONFIG,
    "645": POWER_645_CONFIG,
    "3d": MAX3D_CONFIG,
    "3dpro": MAX3D_PRO_CONFIG,
    "535": LOTTO_535_CONFIG,
    "keno": KENO_CONFIG,
}

# Products that support prediction (power type only)
PREDICTABLE_PRODUCTS = {
    "655": POWER_655_CONFIG,
    "645": POWER_645_CONFIG,
    "535": LOTTO_535_CONFIG,
}


DEFAULT_PREDICTOR_CONFIG = PredictorConfig()
