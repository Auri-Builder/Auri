# agents/ori_wb — ORI Wealth Builder agent
#
# Accumulation-phase financial planning for investors aged ~25–55.
#
# Capabilities:
#   - RRSP vs TFSA contribution optimizer (marginal-tax decision)
#   - Savings rate → FI number → retirement age projector
#   - Asset allocation glide-path model by time horizon and risk tolerance
#   - Portfolio drift detection and rebalancing guidance
#   - Net worth balance sheet (assets minus liabilities)
#
# Data classification: locally stored profile only; no network calls.
# This agent may analyse, model, and project. It may NOT execute trades,
# submit tax forms, or make binding financial commitments on behalf of the user.
#
# Disclaimer: All outputs are for planning and educational purposes only.
# Consult a registered financial advisor before acting on any projections.
