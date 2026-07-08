import re
from abc import ABC, abstractmethod


class BaseTokenizer(ABC):
    """Abstract Base Class for pluggable tokenizers."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Counts the estimated tokens in the given text string."""
        pass


class SimpleTokenizer(BaseTokenizer):
    """Simple tokenizer counting words and punctuation, approximating subword token count.

    Approximates standard GPT BPE models by matching word and non-whitespace/non-word characters,
    then applying a 1.1x multiplier (since small subwords/punctuation average slightly more tokens).
    """

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        # Match words (\w+) and individual punctuation/symbols ([^\w\s])
        tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
        return int(len(tokens) * 1.1)
