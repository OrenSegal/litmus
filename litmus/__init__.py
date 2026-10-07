"""litmus: mutation testing for LLM and agent eval suites.

Can your eval fail? litmus breaks the thing under test on purpose (deletes an
instruction, inverts a rule, truncates a skill) and reruns your eval suite
against each broken copy. The mutation score is the share of broken copies
your evals caught. It also finds graders that cannot fail at all. See SPEC.md.
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
