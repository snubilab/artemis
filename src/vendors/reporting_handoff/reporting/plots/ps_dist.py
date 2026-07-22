"""
Propensity Score distribution plot.
Phase 4.1.4: Overlapping histograms for treated/control PS.
"""
import matplotlib.pyplot as plt
import numpy as np
from typing import Optional


class PSDistPlot:
    """Generate propensity score distribution plots."""
    
    def __init__(
        self, 
        ps_treated: np.ndarray,
        ps_control: np.ndarray,
        figsize: tuple = (10, 6),
        bins: int = 30
    ):
        """
        Args:
            ps_treated: Propensity scores for treated group
            ps_control: Propensity scores for control group
            figsize: Figure size
            bins: Number of histogram bins
        """
        self.ps_treated = ps_treated
        self.ps_control = ps_control
        self.figsize = figsize
        self.bins = bins
        self.fig = None
        self.ax = None
    
    def plot(self) -> plt.Figure:
        """Generate the PS distribution plot."""
        self.fig, self.ax = plt.subplots(figsize=self.figsize)
        
        # Common bin edges
        all_ps = np.concatenate([self.ps_treated, self.ps_control])
        bin_edges = np.linspace(0, 1, self.bins + 1)
        
        # Plot histograms
        self.ax.hist(self.ps_treated, bins=bin_edges, alpha=0.6,
                    label='Treated', color='#1f77b4', edgecolor='black')
        self.ax.hist(self.ps_control, bins=bin_edges, alpha=0.6,
                    label='Control', color='#ff7f0e', edgecolor='black')
        
        # Add statistics
        mean_t = np.mean(self.ps_treated)
        mean_c = np.mean(self.ps_control)
        
        self.ax.axvline(x=mean_t, color='#1f77b4', linestyle='--', linewidth=2)
        self.ax.axvline(x=mean_c, color='#ff7f0e', linestyle='--', linewidth=2)
        
        # Formatting
        self.ax.set_xlabel('Propensity Score', fontsize=12)
        self.ax.set_ylabel('Count', fontsize=12)
        self.ax.set_xlim(0, 1)
        self.ax.legend(loc='upper right')
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        # Add text with statistics
        stats_text = f"Treated: μ={mean_t:.3f}\nControl: μ={mean_c:.3f}"
        self.ax.text(0.02, 0.98, stats_text, transform=self.ax.transAxes,
                    ha='left', va='top', fontsize=9,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        plt.tight_layout()
        return self.fig
    
    def save(self, path: str, dpi: int = 150):
        """Save plot to file."""
        if self.fig is None:
            self.plot()
        self.fig.savefig(path, dpi=dpi, bbox_inches='tight')
        plt.close(self.fig)
