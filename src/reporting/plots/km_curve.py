"""
Kaplan-Meier survival curve plotting.
Phase 4.1.2: Survival curves with confidence bands.
"""
import matplotlib.pyplot as plt
from typing import List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SurvivalCurve:
    """Data for a single survival curve."""
    times: List[float]
    survival: List[float]
    label: str
    ci_lower: Optional[List[float]] = None
    ci_upper: Optional[List[float]] = None


class KMCurvePlot:
    """Generate Kaplan-Meier survival curves."""
    
    def __init__(self, figsize: tuple = (10, 6)):
        self.curves: List[SurvivalCurve] = []
        self.figsize = figsize
        self.fig = None
        self.ax = None
        self.pvalue: Optional[float] = None
    
    def add_curve(
        self,
        times: List[float],
        survival: List[float],
        label: str,
        ci_lower: Optional[List[float]] = None,
        ci_upper: Optional[List[float]] = None
    ):
        """Add a survival curve to the plot."""
        self.curves.append(SurvivalCurve(
            times=times,
            survival=survival,
            label=label,
            ci_lower=ci_lower,
            ci_upper=ci_upper
        ))
    
    def set_logrank_pvalue(self, pvalue: float):
        """Set log-rank test p-value to display."""
        self.pvalue = pvalue
    
    def plot(self) -> plt.Figure:
        """Generate the KM curve plot."""
        self.fig, self.ax = plt.subplots(figsize=self.figsize)
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
        
        for i, curve in enumerate(self.curves):
            color = colors[i % len(colors)]
            
            # Plot survival curve
            self.ax.step(curve.times, curve.survival, where='post',
                        label=curve.label, color=color, linewidth=2)
            
            # Plot confidence interval if available
            if curve.ci_lower and curve.ci_upper:
                self.ax.fill_between(
                    curve.times, curve.ci_lower, curve.ci_upper,
                    alpha=0.2, step='post', color=color
                )
        
        # Add p-value annotation
        if self.pvalue is not None:
            pval_text = f"Log-rank p = {self.pvalue:.4f}"
            if self.pvalue < 0.001:
                pval_text = "Log-rank p < 0.001"
            self.ax.text(0.95, 0.95, pval_text, transform=self.ax.transAxes,
                        ha='right', va='top', fontsize=10,
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        # Formatting
        self.ax.set_xlabel('Time (days)', fontsize=12)
        self.ax.set_ylabel('Survival Probability', fontsize=12)
        self.ax.set_ylim(0, 1.05)
        self.ax.legend(loc='lower left', fontsize=10)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        plt.tight_layout()
        return self.fig
    
    def save(self, path: str, dpi: int = 150):
        """Save plot to file."""
        if self.fig is None:
            self.plot()
        self.fig.savefig(path, dpi=dpi, bbox_inches='tight')
        plt.close(self.fig)
