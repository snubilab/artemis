"""
Forest Plot for Hazard Ratio visualization.
Phase 4.1.1: Publication-quality forest plots.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class HRDataPoint:
    """A single data point for forest plot."""
    study: str
    hr: float
    ci_lower: float
    ci_upper: float


class ForestPlot:
    """Generate forest plots for hazard ratio visualization."""
    
    def __init__(
        self, 
        data: List[Dict],
        reference_line: float = 1.0,
        figsize: tuple = (10, 6)
    ):
        """
        Args:
            data: List of dicts with keys: study, hr, ci_lower, ci_upper
            reference_line: HR value for reference line (default 1.0)
            figsize: Figure size tuple
        """
        self.data = [HRDataPoint(**d) for d in data]
        self.reference_line = reference_line
        self.figsize = figsize
        self.fig = None
        self.ax = None
    
    def plot(self) -> plt.Figure:
        """Generate the forest plot."""
        self.fig, self.ax = plt.subplots(figsize=self.figsize)
        
        n = len(self.data)
        y_positions = list(range(n, 0, -1))
        
        for i, (point, y) in enumerate(zip(self.data, y_positions)):
            # Plot confidence interval line
            self.ax.hlines(y, point.ci_lower, point.ci_upper, color='black', linewidth=1.5)
            
            # Plot HR point
            self.ax.scatter(point.hr, y, s=100, color='navy', zorder=5)
            
            # Add study label
            self.ax.text(0.01, y, point.study, ha='left', va='center', 
                        transform=self.ax.get_yaxis_transform(), fontsize=10)
        
        # Reference line at HR=1
        self.ax.axvline(x=self.reference_line, color='gray', linestyle='--', linewidth=1)
        
        # Labels and formatting
        self.ax.set_xlabel('Hazard Ratio (95% CI)', fontsize=12)
        self.ax.set_xlim(0, max(p.ci_upper for p in self.data) * 1.2)
        self.ax.set_yticks([])
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['left'].set_visible(False)
        
        plt.tight_layout()
        return self.fig
    
    def save(self, path: str, dpi: int = 150):
        """Save plot to file."""
        if self.fig is None:
            self.plot()
        self.fig.savefig(path, dpi=dpi, bbox_inches='tight')
        plt.close(self.fig)
