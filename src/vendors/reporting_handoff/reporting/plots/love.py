"""
Love Plot for covariate balance visualization.
Phase 4.1.3: SMD before/after matching visualization.
"""
import matplotlib.pyplot as plt
from typing import Dict
from dataclasses import dataclass


class LovePlot:
    """Generate Love plots for covariate balance assessment."""
    
    def __init__(
        self, 
        smd_data: Dict[str, Dict[str, float]],
        threshold: float = 0.1,
        figsize: tuple = (10, 8)
    ):
        """
        Args:
            smd_data: Dict of {covariate: {"before": smd, "after": smd}}
            threshold: Balance threshold (default 0.1)
            figsize: Figure size
        """
        self.smd_data = smd_data
        self.threshold = threshold
        self.figsize = figsize
        self.fig = None
        self.ax = None
    
    def plot(self) -> plt.Figure:
        """Generate the Love plot."""
        self.fig, self.ax = plt.subplots(figsize=self.figsize)
        
        covariates = list(self.smd_data.keys())
        n = len(covariates)
        y_positions = list(range(n))
        
        before_smds = [self.smd_data[c].get("before", 0) for c in covariates]
        after_smds = [self.smd_data[c].get("after", 0) for c in covariates]
        
        # Plot before matching (circles)
        self.ax.scatter(before_smds, y_positions, s=100, marker='o',
                       facecolors='none', edgecolors='red', label='Before', linewidths=2)
        
        # Plot after matching (filled circles)
        self.ax.scatter(after_smds, y_positions, s=100, marker='o',
                       color='blue', label='After')
        
        # Threshold line
        self.ax.axvline(x=self.threshold, color='gray', linestyle='--', 
                       linewidth=1.5, label=f'Threshold ({self.threshold})')
        self.ax.axvline(x=-self.threshold, color='gray', linestyle='--', linewidth=1.5)
        
        # Y-axis labels
        self.ax.set_yticks(y_positions)
        self.ax.set_yticklabels(covariates)
        
        # Formatting
        self.ax.set_xlabel('Standardized Mean Difference (SMD)', fontsize=12)
        self.ax.legend(loc='upper right')
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
