"""InstrumentCache - Load and manage instrument static data"""

import csv
from pathlib import Path
from typing import Dict, List, Optional


class Instrument:
    """Represents an instrument with static data"""
    
    def __init__(self, ric: str, stock_code: str, name: str, board_lot: int, **kwargs):
        self.ric = ric
        self.stock_code = stock_code
        self.name = name
        self.board_lot = board_lot
        self.isin = kwargs.get('isin', '')
        self.category = kwargs.get('category', '')
        self.security_type = kwargs.get('security_type', kwargs.get('sub_category', kwargs.get('Sub-Category', '')))
        self.exchange = kwargs.get('exchange', kwargs.get('Exchange', 'XHKG'))
        self.shortsell_eligible = kwargs.get('shortsell_eligible', 'N') == 'Y'
        self.cas_eligible = kwargs.get('cas_eligible', 'N') == 'Y'
        self.vcm_eligible = kwargs.get('vcm_eligible', 'N') == 'Y'
        self.currency = kwargs.get('currency', 'HKD')

    def to_dict(self) -> Dict[str, str]:
        """Convert instrument to dictionary."""
        return {
            'ric': self.ric,
            'stock_code': self.stock_code,
            'name': self.name,
            'exchange': self.exchange,
            'category': self.category,
            'security_type': self.security_type,
            'board_lot': self.board_lot,
            'isin': self.isin,
            'shortsell': self.shortsell_eligible,
            'cas': self.cas_eligible,
            'vcm': self.vcm_eligible,
            'currency': self.currency,
        }
        
    def __repr__(self):
        return f"Instrument(ric={self.ric}, code={self.stock_code}, name={self.name}, exch={self.exchange})"


class InstrumentCache:
    """Cache for instrument static data from CSV"""
    
    def __init__(self, csv_path: Optional[str] = None):
        self.instruments: Dict[str, Instrument] = {}
        self.ric_to_code: Dict[str, str] = {}
        
        if csv_path:
            self.load_from_csv(csv_path)
    
    def load_from_csv(self, csv_path: str) -> int:
        """
        Load instruments from CSV file
        
        Args:
            csv_path: Path to CSV file (default: HK-ListOfSecurities.csv)
            
        Returns:
            Number of instruments loaded
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Parse board lot (remove commas)
                    board_lot = int(row.get('Board Lot', '0').replace(',', ''))
                    ric = row.get('RIC') or row.get('\ufeffRIC', '')
                    if not ric:
                        continue
                    stock_code = row.get('Stock Code', '')
                    sec_type = row.get('Sub-Category') or row.get('SecurityType') or row.get('Security Type', '')
                    exchange = row.get('Exchange') or row.get('exchange', 'XHKG')
                    
                    instrument = Instrument(
                        ric=ric,
                        stock_code=stock_code,
                        name=row.get('Name of Securities', ''),
                        board_lot=board_lot,
                        isin=row.get('ISIN', ''),
                        category=row.get('Category', ''),
                        security_type=sec_type,
                        exchange=exchange,
                        shortsell_eligible=row.get('Shortsell Eligible', 'N'),
                        cas_eligible=row.get('CAS Eligible', 'N'),
                        vcm_eligible=row.get('VCM Eligible', 'N'),
                        currency=row.get('Trading Currency', 'HKD')
                    )
                    
                    self.instruments[instrument.ric] = instrument
                    if stock_code:
                        self.ric_to_code[instrument.ric] = stock_code
                    count += 1
                except (ValueError, KeyError) as e:
                    print(f"Warning: Failed to parse row {row}: {e}")
                    continue
        
        return count
    
    def get_instrument(self, symbol_or_ric: str) -> Optional[Instrument]:
        """Get instrument by RIC masterkey (or fallback stock code)"""
        if not symbol_or_ric:
            return None
        # Primary lookup: RIC masterkey
        if symbol_or_ric in self.instruments:
            return self.instruments[symbol_or_ric]
        # Secondary lookup: stock code
        return self.get_by_code(symbol_or_ric)
    
    def get_by_code(self, code: str) -> Optional[Instrument]:
        """Get instrument by stock code"""
        for instrument in self.instruments.values():
            if instrument.stock_code == code:
                return instrument
        return None
    
    def list_all(self) -> List[Instrument]:
        """Get all instruments"""
        return list(self.instruments.values())
    
    def count(self) -> int:
        """Total number of instruments"""
        return len(self.instruments)

    def add_or_update_instrument(self, data: Dict[str, Any]) -> Instrument:
        """Add or update an instrument entry in memory cache."""
        ric = str(data.get('ric', '') or '').strip()
        if not ric:
            raise ValueError("RIC is required")
            
        stock_code = str(data.get('stock_code', '') or '').strip()
        name = str(data.get('name', '') or '').strip()
        board_lot = int(data.get('board_lot', 100) or 100)
        isin = str(data.get('isin', '') or '').strip()
        category = str(data.get('category', '') or '').strip()
        security_type = str(data.get('security_type', data.get('sub_category', '')) or '').strip()
        exchange = str(data.get('exchange', 'XHKG') or 'XHKG').strip()
        
        shortsell = 'Y' if data.get('shortsell') in (True, 'Y', 'y', 1, '1') else 'N'
        cas = 'Y' if data.get('cas') in (True, 'Y', 'y', 1, '1') else 'N'
        vcm = 'Y' if data.get('vcm') in (True, 'Y', 'y', 1, '1') else 'N'
        currency = str(data.get('currency', 'HKD') or 'HKD').strip()

        inst = Instrument(
            ric=ric,
            stock_code=stock_code,
            name=name,
            board_lot=board_lot,
            isin=isin,
            category=category,
            security_type=security_type,
            exchange=exchange,
            shortsell_eligible=shortsell,
            cas_eligible=cas,
            vcm_eligible=vcm,
            currency=currency
        )
        self.instruments[ric] = inst
        if stock_code:
            self.ric_to_code[ric] = stock_code
        return inst

    def delete_instrument(self, ric: str) -> bool:
        """Delete instrument from memory cache by RIC."""
        if ric in self.instruments:
            inst = self.instruments.pop(ric)
            if ric in self.ric_to_code:
                del self.ric_to_code[ric]
            return True
        return False
