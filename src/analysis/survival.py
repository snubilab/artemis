"""
Survival analysis utilities.
Phase 3.2: Time-to-event calculation and censoring.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple, Optional


@dataclass
class SurvivalRecord:
    """A single survival analysis record."""
    person_id: int
    treatment_group: str  # 'target' or 'comparator'
    time: float  # Time in days
    event: int  # 0=censored, 1=event occurred
    covariates: Dict[str, float] = None
    
    def __post_init__(self):
        if self.covariates is None:
            self.covariates = {}


def calculate_time_to_event(index_date: date, event_date: date) -> int:
    """
    Calculate time from index date to event date.
    
    Args:
        index_date: Cohort start date
        event_date: Date of outcome event
        
    Returns:
        Number of days between dates
    """
    delta = event_date - index_date
    return delta.days


def apply_censoring(
    index_date: date,
    event_date: Optional[date],
    tar_days: int,
    observation_end: Optional[date] = None
) -> Tuple[int, int]:
    """
    Apply censoring based on time-at-risk window.
    
    Args:
        index_date: Cohort start date
        event_date: Date of outcome event (None if no event)
        tar_days: Time-at-risk window in days
        observation_end: End of observation period
        
    Returns:
        Tuple of (censored_time, event_indicator)
        - event_indicator: 1 if event occurred within TAR, 0 if censored
    """
    from datetime import timedelta
    
    tar_end = index_date + timedelta(days=tar_days)
    
    # Determine the effective end date
    effective_end = tar_end
    if observation_end and observation_end < tar_end:
        effective_end = observation_end
    
    # If no event, censored at effective end
    if event_date is None:
        time_days = (effective_end - index_date).days
        return time_days, 0
    
    # If event after TAR window, censored at TAR end
    if event_date > tar_end:
        return tar_days, 0
    
    # If event after observation end, censored
    if observation_end and event_date > observation_end:
        time_days = (observation_end - index_date).days
        return time_days, 0
    
    # Event occurred within window
    time_days = (event_date - index_date).days
    return time_days, 1


@dataclass
class SurvivalDataset:
    """Collection of survival records for analysis."""
    records: list
    
    def to_dataframe(self):
        """Convert to pandas DataFrame."""
        import pandas as pd
        
        data = []
        for r in self.records:
            row = {
                'person_id': r.person_id,
                'treatment_group': r.treatment_group,
                'time': r.time,
                'event': r.event,
                **r.covariates
            }
            data.append(row)
        
        return pd.DataFrame(data)
