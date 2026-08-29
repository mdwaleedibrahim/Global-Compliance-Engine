"""Rule Engine — Controls Selection for GCE Pre-Trade Risk System.

Implements order-to-rule matching using the full set of TEXT_KEY_COLUMNS with:
  * (ALL)      — matches any value
  $ (Override) — matched only if no other rule matches this column with exact value or *
  exact text   — case-insensitive exact match

Multi-rule execution:
  All matched/enabled rules are selected.
  Controls are executed once per matched rule using that rule's own limits.
  The order passes only if it passes every matched rule.
  A limit of 0 in a rule means that control is disabled for that rule.

$ scope:
  Per-column. A rule may contain at most 1 $ across all its key columns.
  A $ column matches only when no other rule produces an exact-match on that same column
  for the given order. Wildcards (*) do NOT count as overrides of $.
"""

from typing import Any, Dict, List, Optional, Tuple

from gce.datamgr import (
    RMSLimitRule,
    TEXT_KEY_COLUMNS,
    NUMERICAL_COLUMNS,
    CORE_NUMERICAL_COLUMNS,
    ALL_DB_COLUMNS,
)

# Wildcard constants
WILDCARD_ALL = '*'
WILDCARD_OVERRIDE = '$'


class MatchResult:
    """Result of matching a single RMSLimitRule against order attributes."""

    def __init__(self, rule: RMSLimitRule, matched: bool,
                 score: int, override_columns: List[str]):
        self.rule = rule
        self.matched = matched
        # Number of exact (non-wildcard) column matches
        self.score = score
        # Columns where this rule matched via $ (override)
        self.override_columns = override_columns

    def __repr__(self):
        return (f"MatchResult(DBId={self.rule.db_id}, matched={self.matched}, "
                f"score={self.score}, overrides={self.override_columns})")


def _normalise(v: Any) -> str:
    """Normalise a value for comparison: strip, uppercase."""
    return str(v or '').strip().upper()


class RuleEngine:
    """
    Selects applicable RMS limit rules for an order and merges limits.

    Usage::

        re = RuleEngine()
        attrs = re.build_order_attrs(order, datamgr)
        rules = re.select_rules(attrs, datamgr._rms_limits)
        merged = re.merge_limits(rules)
    """

    # ------------------------------------------------------------------
    # Step 1 — Build order attributes from order + instrument cache
    # ------------------------------------------------------------------

    def build_order_attrs(self, order: Any, datamgr: Any) -> Dict[str, str]:
        """
        Derive all TEXT_KEY_COLUMN values for the order.

        Sources:
          - InstrumentCache / DataMgr for Product, SecurityType, exchange, underlying
          - Order object fields for all other columns

        Returns:
            Dict[column_name -> normalised string value]
        """
        attrs: Dict[str, str] = {}

        # Order-derived fields
        o = order if not isinstance(order, dict) else None
        d = order if isinstance(order, dict) else None

        def oget(attr: str, default: str = '') -> str:
            if o is not None:
                return str(getattr(o, attr, '') or '').strip()
            return str((d or {}).get(attr, '') or '').strip()

        ric = oget('ric') or oget('symbol')

        # Resolve instrument static data
        inst = None
        if datamgr and ric:
            inst = (
                getattr(datamgr, 'get_instrument', lambda x: None)(ric)
                or getattr(datamgr, 'instruments', {}).get(ric)
            )

        # Product → instrument.category
        product = oget('product')
        if not product and inst:
            product = str(getattr(inst, 'category', '') or '').strip()
        attrs['Product'] = product

        # SecurityType → instrument.sub_category / security_type
        sec_type = oget('security_type')
        if not sec_type and inst:
            sec_type = str(
                getattr(inst, 'sub_category', '') or
                getattr(inst, 'security_type', '') or ''
            ).strip()
        attrs['SecurityType'] = sec_type

        # Application, Flow, Trader, Desk, Account, Client — order fields
        attrs['Application'] = oget('application')
        attrs['Flow'] = oget('flow')
        attrs['Trader'] = oget('trader')
        attrs['Desk'] = oget('desk')
        attrs['Account'] = oget('account')
        attrs['Client'] = oget('client')

        # symbol → order RIC
        attrs['symbol'] = ric

        # exchange → instrument.exchange, fallback order.exchange
        exchange = ''
        if inst:
            exchange = str(getattr(inst, 'exchange', '') or '').strip()
        if not exchange:
            exchange = oget('exchange')
        attrs['exchange'] = exchange

        # underlying → instrument.stock_code, fallback order.underlying
        underlying = ''
        if inst:
            underlying = str(getattr(inst, 'stock_code', '') or '').strip()
        if not underlying:
            underlying = oget('underlying')
        attrs['underlying'] = underlying

        # AlgoStrategy — order field
        attrs['AlgoStrategy'] = oget('algo_strategy') or oget('algo')

        # Currency — order field, fallback instrument.currency
        currency = oget('currency')
        if not currency and inst:
            currency = str(getattr(inst, 'currency', '') or '').strip()
        attrs['Currency'] = currency

        # Side, OrderType, Tif — order fields
        attrs['Side'] = oget('side')
        attrs['OrderType'] = oget('order_type')
        attrs['Tif'] = oget('tif')

        # ExtendedKey1–5 — reserved, empty for now
        for k in ('ExtendedKey1', 'ExtendedKey2', 'ExtendedKey3', 'ExtendedKey4', 'ExtendedKey5'):
            attrs[k] = oget(k.lower()) or oget(k)

        return attrs

    # ------------------------------------------------------------------
    # Step 2 — Evaluate a single rule against order attributes
    # ------------------------------------------------------------------

    def _match_rule(self, rule: RMSLimitRule, attrs: Dict[str, str]) -> MatchResult:
        """
        Evaluate one rule against derived order attributes.

        Returns:
            MatchResult with matched=True/False, score, and override_columns list.
        """
        score = 0
        override_columns: List[str] = []

        for col in TEXT_KEY_COLUMNS:
            rule_val = _normalise(rule.keys.get(col, WILDCARD_ALL))
            order_val = _normalise(attrs.get(col, ''))

            if rule_val == WILDCARD_ALL:
                # * matches everything — no score increment
                continue

            if rule_val == WILDCARD_OVERRIDE:
                # $ — tentatively matches, but deferred (may be overridden)
                override_columns.append(col)
                continue

            # Exact match required
            if not order_val:
                # Order does not specify this field — treat as match (permissive)
                continue

            if rule_val != order_val:
                return MatchResult(rule, matched=False, score=0, override_columns=[])

            score += 1

        return MatchResult(rule, matched=True, score=score, override_columns=override_columns)

    # ------------------------------------------------------------------
    # Step 3 — Select rules with $ override resolution
    # ------------------------------------------------------------------

    def select_rules(self, attrs: Dict[str, str],
                     rms_limits: List[RMSLimitRule]) -> List[RMSLimitRule]:
        """
        Select all applicable RMS limit rules for the given order attributes.

        Algorithm:
          1. Exclude rules where Enabled != 'Y'
          2. Match each rule against attrs
          3. Resolve $ columns:
             For each $ column, the $ rule is kept only if no other matched rule
             has an exact match or * for that column (i.e., truly no alternative).
          4. Return all surviving matched rules

        Returns:
            List of selected RMSLimitRule objects
        """
        # Phase 1: match all enabled rules
        candidates: List[MatchResult] = []
        for rule in rms_limits:
            if _normalise(rule.flags.get('Enabled', 'Y')) != 'Y':
                continue
            mr = self._match_rule(rule, attrs)
            if mr.matched:
                candidates.append(mr)

        if not candidates:
            return []

        # Phase 2: for each $ column, determine if a non-$ *exact-match* alternative exists
        # Only exact (specific) matches override $. Wildcards (*) do NOT count as overrides
        # because * rules are catch-all defaults that should always apply.
        non_override_covered: Dict[str, bool] = {}
        for mr in candidates:
            for col in TEXT_KEY_COLUMNS:
                rule_val = _normalise(mr.rule.keys.get(col, WILDCARD_ALL))
                if rule_val not in (WILDCARD_OVERRIDE, WILDCARD_ALL) and col not in non_override_covered:
                    non_override_covered[col] = True

        # Phase 3: filter — keep a rule only if all its $ columns lack non-$ alternatives
        selected: List[RMSLimitRule] = []
        for mr in candidates:
            if not mr.override_columns:
                # No $ columns — keep unconditionally
                selected.append(mr.rule)
                continue

            # Check each override column: drop rule if any $ col already has a non-$ match
            discard = False
            for col in mr.override_columns:
                if non_override_covered.get(col):
                    discard = True
                    break

            if not discard:
                selected.append(mr.rule)

        return selected

    # ------------------------------------------------------------------
    # Step 4 — Build per-rule limit context dicts
    # ------------------------------------------------------------------

    def get_per_rule_contexts(self, selected_rules: List[RMSLimitRule],
                               base_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build one context dict per selected rule, each containing that rule's own limits.

        Returns:
            List of context dicts (one per rule), each augmented with:
              - 'rule_limits': the rule's to_dict() limits
              - 'rule_id': the rule's DBId
              - 'datamgr': overridden get_matching_limits returns this rule's limits directly
        """
        if not selected_rules:
            # No rules matched — return single context with all-zero limits (controls disabled)
            empty = dict(base_context)
            empty['rule_limits'] = self._empty_limits()
            empty['rule_id'] = None
            empty['datamgr'] = _SingleRuleDataMgr(empty['rule_limits'],
                                                   base_context.get('datamgr'))
            return [empty]

        contexts = []
        for rule in selected_rules:
            ctx = dict(base_context)
            rule_dict = rule.to_dict()
            ctx['rule_limits'] = rule_dict
            ctx['rule_id'] = rule.db_id
            # Wrap datamgr so controls calling get_matching_limits() get this rule's limits
            ctx['datamgr'] = _SingleRuleDataMgr(rule_dict, base_context.get('datamgr'))
            contexts.append(ctx)
        return contexts

    def _empty_limits(self) -> Dict[str, Any]:
        """Return all-zero limits dict (no rules matched → all controls disabled)."""
        result: Dict[str, Any] = {'DBId': None}
        for col in TEXT_KEY_COLUMNS:
            result[col] = WILDCARD_ALL
        for col in NUMERICAL_COLUMNS:
            result[col] = 0.0
        result.update({
            'DuplicateOrders': '0', 'BurstOrders': '0',
            'Restricted': 'N', 'SSRestricted': 'N', 'Enabled': 'Y',
        })
        return result

    def merge_limits(self, selected_rules: List[RMSLimitRule]) -> Dict[str, Any]:
        """
        Merge numerical limits across all selected rules.

        For each limit column:
          - If all rules have 0 → control is disabled (merged value = 0)
          - Otherwise → take the minimum non-zero value (most restrictive)

        Flag columns (Restricted, SSRestricted, DuplicateOrders, BurstOrders):
          - Restricted / SSRestricted: 'Y' if any rule has 'Y' (logical OR)
          - DuplicateOrders / BurstOrders: most restrictive non-zero spec

        Returns:
            Merged dict suitable as a drop-in replacement for datamgr.get_matching_limits()
        """
        if not selected_rules:
            # No rules matched — all limits are 0 (disabled)
            result: Dict[str, Any] = {'DBId': None}
            for col in TEXT_KEY_COLUMNS:
                result[col] = WILDCARD_ALL
            for col in NUMERICAL_COLUMNS:
                result[col] = 0.0
            result.update({
                'DuplicateOrders': '0',
                'BurstOrders': '0',
                'Restricted': 'N',
                'SSRestricted': 'N',
                'Enabled': 'Y',
                '_matched_rules': [],
            })
            return result

        merged: Dict[str, Any] = {
            'DBId': [r.db_id for r in selected_rules],
            '_matched_rules': [r.db_id for r in selected_rules],
        }

        # Key columns — take from highest-priority rule (first selected)
        for col in TEXT_KEY_COLUMNS:
            merged[col] = selected_rules[0].keys.get(col, WILDCARD_ALL)

        # Numerical limits — minimum non-zero (most restrictive), 0 if all zero
        for col in NUMERICAL_COLUMNS:
            non_zero_vals = [
                r.limits[col] for r in selected_rules
                if r.limits.get(col, 0.0) > 0.0
            ]
            merged[col] = min(non_zero_vals) if non_zero_vals else 0.0

        # Restricted / SSRestricted — Y if any rule says Y
        merged['Restricted'] = (
            'Y' if any(r.flags.get('Restricted', 'N') == 'Y' for r in selected_rules) else 'N'
        )
        merged['SSRestricted'] = (
            'Y' if any(r.flags.get('SSRestricted', 'N') == 'Y' for r in selected_rules) else 'N'
        )

        # DuplicateOrders / BurstOrders — most restrictive non-zero
        merged['DuplicateOrders'] = self._merge_rate_limit(
            [r.flags.get('DuplicateOrders', '0') for r in selected_rules]
        )
        merged['BurstOrders'] = self._merge_rate_limit(
            [r.flags.get('BurstOrders', '0') for r in selected_rules]
        )

        merged['Enabled'] = 'Y'
        return merged

    def _merge_rate_limit(self, specs: List[str]) -> str:
        """
        Merge rate limit specs ('x,y' or '0'). Returns most restrictive (lowest max_orders).
        """
        from gce.datamgr import parse_rate_limit_spec
        parsed = [parse_rate_limit_spec(s) for s in specs]
        valid = [p for p in parsed if p is not None]
        if not valid:
            return '0'
        # Most restrictive = lowest max_orders in shortest window
        best = min(valid, key=lambda p: (p[0], p[1]))
        return f"{best[0]},{best[1]}"

    # ------------------------------------------------------------------
    # Step 5 — Determine active controls for selected rules
    # ------------------------------------------------------------------

    def get_active_control_limits(self, merged_limits: Dict[str, Any],
                                  registered_control_names: List[str]) -> Dict[str, float]:
        """
        Return control_name → limit mapping for controls that are active (limit > 0).

        Maps registered control names to limit columns:
          max_qty            → MaxOrderSize (also MaxOrderQuantity)
          max_price          → MaxOrderPrice
          max_consideration  → MaxOrderValue
          bbo_tolerance      → BBOPriceTolerance
          close_tolerance    → ClosePriceTolerance
          last_tolerance     → LastPriceTolerance

        Returns:
            Dict[control_name -> limit_value] for controls with limit > 0
        """
        CONTROL_TO_LIMIT_COL: Dict[str, List[str]] = {
            'MaxOrderQuantity':     ['MaxOrderSize', 'MaxOrderQuantity'],
            'MaxOrderPrice':        ['MaxOrderPrice'],
            'MaxOrderConsideration': ['MaxOrderValue'],
            'BBOPriceTolerance':    ['BBOPriceTolerance'],
            'ClosePriceTolerance':  ['ClosePriceTolerance'],
            'LastPriceTolerance':   ['LastPriceTolerance'],
            'max_qty':              ['MaxOrderSize', 'MaxOrderQuantity'],
            'max_price':            ['MaxOrderPrice'],
            'max_consideration':    ['MaxOrderValue'],
            'bbo_tolerance':        ['BBOPriceTolerance'],
            'close_tolerance':      ['ClosePriceTolerance'],
            'last_tolerance':       ['LastPriceTolerance'],
        }

        active: Dict[str, float] = {}
        for ctrl_name in registered_control_names:
            cols = CONTROL_TO_LIMIT_COL.get(ctrl_name)
            if not cols:
                # Unknown mapping — include by default with limit=0 (control decides)
                active[ctrl_name] = 0.0
                continue
            limit = 0.0
            for col in cols:
                val = float(merged_limits.get(col, 0.0) or 0.0)
                if val > 0.0:
                    limit = val
                    break
            if limit > 0.0:
                active[ctrl_name] = limit
        return active


class _SingleRuleDataMgr:
    """
    Lightweight DataMgr proxy that short-circuits get_matching_limits() to
    always return a specific rule's pre-computed limits dict.

    All other DataMgr methods are delegated to the real datamgr instance.
    This allows controls that call context['datamgr'].get_matching_limits(order)
    to receive exactly the limits for the rule currently being evaluated,
    without re-running the full rule selection algorithm.
    """

    def __init__(self, rule_limits: Dict[str, Any], real_datamgr: Any):
        self._rule_limits = rule_limits
        self._real = real_datamgr

    def get_matching_limits(self, order: Any = None) -> Dict[str, Any]:
        """Always return the pre-resolved rule limits for this execution context."""
        return self._rule_limits

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attribute access to the real DataMgr instance."""
        if self._real is not None:
            return getattr(self._real, name)
        raise AttributeError(f"_SingleRuleDataMgr has no attribute '{name}'")
