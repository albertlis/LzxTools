import pickle
from abc import ABC, abstractmethod
from pathlib import Path

from zstandard import ZstdDecompressor, ZstdCompressor


class ScrapperBase(ABC):
    def __init__(self, cache_path: Path):
        super().__init__()
        self.cache_path = cache_path
        self.cache = self.load_cache()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        }

    @staticmethod
    @abstractmethod
    def new_offers_to_dict(new_offers) -> list[dict[str, str]]:
        pass

    def load_cache(self):
        path = Path(self.cache_path)
        if path.exists():
            with open(path, 'rb') as f:
                data = f.read()
            data = ZstdDecompressor().decompress(data)
            return pickle.loads(data)
        return set()

    def save_cache(self):
        data = pickle.dumps(self.cache, protocol=pickle.HIGHEST_PROTOCOL)
        data = ZstdCompressor().compress(data)
        with open(self.cache_path, 'wb') as f:
            f.write(data)

    def __del__(self):
        self.save_cache()
