
"""
Pure Bayesian Adaptive Preference Testing Algorithm
Version: 3.1
Author: Based on research by Kingsley (2009), Brochu et al. (2010)

This is the CORE algorithm that:
1. Maintains Bayesian belief about preference ordering
2. Selects maximally informative pairs to present
3. Updates beliefs based on observed choices
4. Converges to true preference ranking

References:
- Kingsley, D. C. (2009). Preference uncertainty, preference refinement and paired comparison choice experiments.
- Brochu, E., Cora, V. M., & de Freitas, N. (2010). A tutorial on Bayesian optimization of expensive cost functions.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize
from typing import Tuple, List, Optional
import logging

logger = logging.getLogger(__name__)


class BayesianPreferenceState:
    """
    Maintains the Bayesian state for preference learning.
    
    State consists of:
    - mu: n-dimensional vector of preference means (higher = more preferred)
    - Sigma: n×n covariance matrix representing uncertainty
    - comparison_matrix: n×n matrix tracking which pairs have been compared
    """
    
    def __init__(self, n_items: int, prior_mean: float = 0.0, prior_variance: float = 1.0):
        """
        Initialize Bayesian state.
        
        Args:
            n_items: Number of items (stimuli)
            prior_mean: Prior mean preference for all items
            prior_variance: Prior variance (uncertainty) for all items
        """
        self.n_items = n_items
        self.mu = np.ones(n_items) * prior_mean
        self.Sigma = np.eye(n_items) * prior_variance
        self.comparison_matrix = np.zeros((n_items, n_items), dtype=int)
        
        logger.info(f"Initialized Bayesian state: {n_items} items, "
                   f"prior μ={prior_mean}, σ²={prior_variance}")
    
    def to_dict(self) -> dict:
        """Serialize state to dictionary."""
        return {
            'n_items': self.n_items,
            'mu': self.mu.tolist(),
            'Sigma': self.Sigma.tolist(),
            'comparison_matrix': self.comparison_matrix.tolist()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'BayesianPreferenceState':
        """Deserialize state from dictionary."""
        state = cls(data['n_items'])
        state.mu = np.array(data['mu'])
        state.Sigma = np.array(data['Sigma'])
        state.comparison_matrix = np.array(data['comparison_matrix'])
        return state
    
    def get_preference_ranking(self) -> List[int]:
        """
        Get current preference ranking (best to worst).
        
        Returns:
            List of item indices sorted by preference (descending)
        """
        return np.argsort(-self.mu).tolist()
    
    def get_uncertainties(self) -> np.ndarray:
        """
        Get uncertainty (standard deviation) for each item.
        
        Returns:
            Array of uncertainties
        """
        return np.sqrt(np.diag(self.Sigma))


class PureBayesianAdaptiveSelector:
    """
    Pure Bayesian adaptive pair selector using information gain.
    
    This algorithm selects pairs that maximize expected information gain about
    the preference ordering. It is "pure" in the sense that it:
    - Has no database dependencies
    - Contains only the mathematical algorithm
    - Is testable in isolation
    - Follows functional programming principles
    """
    
    def __init__(self, epsilon: float = 0.01, exploration_weight: float = 0.1):
        """
        Initialize selector.
        
        Args:
            epsilon: Noise parameter in Bradley-Terry model (P(i>j) = Φ((μᵢ-μⱼ)/ε))
            exploration_weight: Weight for exploration vs exploitation (0=pure exploit, 1=pure explore)
        """
        self.epsilon = epsilon
        self.exploration_weight = exploration_weight
        logger.info(f"Initialized selector: ε={epsilon}, exploration={exploration_weight}")
    
    def select_next_pair(self, state: BayesianPreferenceState) -> Tuple[int, int]:
        """
        Select the next pair to present using information gain criterion.
        
        Algorithm:
        1. For each possible pair (i,j):
            a. Calculate P(choose i | current belief)
            b. Calculate expected information gain
        2. Return pair with maximum expected information gain
        
        Args:
            state: Current Bayesian state
            
        Returns:
            Tuple (i, j) where i and j are item indices
        """
        n = state.n_items
        
        # Calculate information gain for all possible pairs
        max_gain = -np.inf
        best_pair = (0, 1)
        
        for i in range(n):
            for j in range(i + 1, n):
                # Calculate expected information gain for this pair
                gain = self._expected_information_gain(i, j, state)
                
                # Add exploration bonus (favors less-compared pairs)
                comparisons = state.comparison_matrix[i, j] + state.comparison_matrix[j, i]
                exploration_bonus = self.exploration_weight / (1 + comparisons)
                
                total_score = gain + exploration_bonus
                
                if total_score > max_gain:
                    max_gain = total_score
                    best_pair = (i, j)
        
        logger.debug(f"Selected pair {best_pair} with gain {max_gain:.4f}")
        return best_pair
    
    def _expected_information_gain(self, i: int, j: int, state: BayesianPreferenceState) -> float:
        """
        Calculate expected information gain for comparing items i and j.
        
        Information gain measures how much we expect to learn from this comparison.
        High gain occurs when:
        - We're uncertain about the relative preference
        - The items are close in current preference estimate
        
        Args:
            i, j: Item indices to compare
            state: Current Bayesian state
            
        Returns:
            Expected information gain
        """
        # Current belief about difference: μᵢ - μⱼ
        mu_diff = state.mu[i] - state.mu[j]
        
        # Uncertainty in the difference (from covariance)
        sigma_diff = np.sqrt(state.Sigma[i, i] + state.Sigma[j, j] - 2 * state.Sigma[i, j])
        
        # Probability that i is preferred over j
        p_i_over_j = norm.cdf(mu_diff / (self.epsilon + sigma_diff))
        
        # Information gain is highest when p ≈ 0.5 (maximum uncertainty about outcome)
        # and when uncertainty (sigma_diff) is high
        gain = -p_i_over_j * np.log2(p_i_over_j + 1e-10)
        gain += -(1 - p_i_over_j) * np.log2(1 - p_i_over_j + 1e-10)
        gain *= sigma_diff  # Weight by uncertainty
        
        return gain
    
    def update_beliefs(self, state: BayesianPreferenceState, 
                       i: int, j: int, winner: int) -> BayesianPreferenceState:
        """
        Update Bayesian beliefs based on observed choice.
        
        Uses the Bradley-Terry model with Gaussian approximation:
        P(i > j | μ, Σ) = Φ((μᵢ - μⱼ) / √(σᵢ² + σⱼ² - 2σᵢⱼ + ε²))
        
        Update is performed using a Gaussian approximation to the posterior.
        
        Args:
            state: Current Bayesian state
            i, j: Item indices that were compared
            winner: Index of chosen item (must be i or j)
            
        Returns:
            Updated state
        """
        if winner not in [i, j]:
            raise ValueError(f"Winner {winner} must be either {i} or {j}")
        
        # Track comparison
        state.comparison_matrix[i, j] += 1
        
        # Preference difference and uncertainty
        mu_diff = state.mu[i] - state.mu[j]
        sigma_diff_sq = (state.Sigma[i, i] + state.Sigma[j, j] - 
                         2 * state.Sigma[i, j] + self.epsilon**2)
        sigma_diff = np.sqrt(sigma_diff_sq)
        
        # Probability of observed outcome
        if winner == i:
            p_obs = norm.cdf(mu_diff / sigma_diff)
        else:
            p_obs = norm.cdf(-mu_diff / sigma_diff)
        
        # Gradient of log-likelihood (for mean update)
        z = mu_diff / sigma_diff
        if winner == i:
            dlnL_dz = norm.pdf(z) / (norm.cdf(z) + 1e-10)
        else:
            dlnL_dz = -norm.pdf(z) / (norm.cdf(-z) + 1e-10)
        
        # Update mean (Laplace approximation)
        dmu = dlnL_dz / sigma_diff
        state.mu[i] += state.Sigma[i, i] * dmu - state.Sigma[i, j] * dmu
        state.mu[j] += state.Sigma[j, i] * dmu - state.Sigma[j, j] * dmu
        
        # Update covariance (information matrix approximation)
        # The observation provides information proportional to the derivative
        info_gain = (norm.pdf(z) / (p_obs * (1 - p_obs) + 1e-10))**2 / sigma_diff_sq
        
        # Rank-1 update to covariance
        v = np.zeros(state.n_items)
        v[i] = 1.0 / sigma_diff
        v[j] = -1.0 / sigma_diff
        
        # Sherman-Morrison formula: (A + uv^T)^{-1} = A^{-1} - (A^{-1}uv^T A^{-1})/(1 + v^T A^{-1}u)
        Sigma_v = state.Sigma @ v
        state.Sigma -= info_gain * np.outer(Sigma_v, Sigma_v) / (1 + info_gain * v @ Sigma_v)
        
        logger.debug(f"Updated beliefs: {winner} chosen over {i if winner==j else j}, "
                    f"μ_diff={mu_diff:.3f}, p={p_obs:.3f}")
        
        return state
    
    def check_convergence(self, state: BayesianPreferenceState, 
                         threshold: float = 0.05) -> bool:
        """
        Check if beliefs have converged.
        
        Convergence occurs when uncertainties are below threshold.
        
        Args:
            state: Current Bayesian state
            threshold: Uncertainty threshold
            
        Returns:
            True if converged
        """
        uncertainties = state.get_uncertainties()
        max_uncertainty = np.max(uncertainties)
        
        converged = max_uncertainty < threshold
        
        if converged:
            logger.info(f"Converged: max uncertainty {max_uncertainty:.4f} < {threshold}")
        
        return converged


class ExperimentSession:
    """
    Manages a complete experiment session for one subject.
    
    This orchestrates the experiment flow:
    1. Initialize Bayesian state
    2. Loop: select pair → present → record choice → update
    3. Terminate when converged or max trials reached
    """
    
    def __init__(self, n_items: int, max_trials: int = 50, 
                 selector: Optional[PureBayesianAdaptiveSelector] = None,
                 prior_mean: float = 0.0, prior_variance: float = 1.0):
        """
        Initialize experiment session.
        
        Args:
            n_items: Number of items (stimuli)
            max_trials: Maximum number of comparisons
            selector: Pair selector (if None, uses default)
            prior_mean: Prior mean preference
            prior_variance: Prior variance
        """
        self.state = BayesianPreferenceState(n_items, prior_mean, prior_variance)
        self.selector = selector or PureBayesianAdaptiveSelector()
        self.max_trials = max_trials
        self.trial_count = 0
        self.choices = []
        
        logger.info(f"Started session: {n_items} items, max {max_trials} trials")
    
    def get_next_pair(self) -> Optional[Tuple[int, int]]:
        """
        Get next pair to present.
        
        Returns:
            (i, j) tuple or None if session complete
        """
        if self.trial_count >= self.max_trials:
            logger.info(f"Session complete: reached max trials ({self.max_trials})")
            return None
        
        if self.selector.check_convergence(self.state):
            logger.info(f"Session complete: converged after {self.trial_count} trials")
            return None
        
        pair = self.selector.select_next_pair(self.state)
        return pair
    
    def record_choice(self, i: int, j: int, winner: int, response_time_ms: Optional[int] = None):
        """
        Record a choice and update beliefs.
        
        Args:
            i, j: Items that were compared
            winner: Chosen item
            response_time_ms: Response time in milliseconds
        """
        self.state = self.selector.update_beliefs(self.state, i, j, winner)
        
        self.choices.append({
            'trial': self.trial_count + 1,
            'item_a': i,
            'item_b': j,
            'chosen': winner,
            'response_time_ms': response_time_ms
        })
        
        self.trial_count += 1
        
        logger.info(f"Trial {self.trial_count}: items ({i},{j}), chose {winner}, "
                   f"RT={response_time_ms}ms")
    
    def get_results(self) -> dict:
        """
        Get final results.
        
        Returns:
            Dictionary with ranking, preferences, uncertainties, and choices
        """
        ranking = self.state.get_preference_ranking()
        preferences = self.state.mu.tolist()
        uncertainties = self.state.get_uncertainties().tolist()
        
        return {
            'trials_completed': self.trial_count,
            'ranking': ranking,
            'preferences': preferences,
            'uncertainties': uncertainties,
            'choices': self.choices,
            'converged': self.selector.check_convergence(self.state)
        }


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_algorithm_with_ground_truth(n_items: int = 10, n_trials: int = 50, 
                                        noise: float = 0.1) -> dict:
    """
    Validate algorithm by recovering a known preference ordering.
    
    This is critical for scientific validity:
    1. Generate ground truth preferences
    2. Simulate choices based on ground truth (with noise)
    3. Run algorithm
    4. Check if recovered preferences match ground truth
    
    Args:
        n_items: Number of items
        n_trials: Number of trials
        noise: Noise in simulated choices
        
    Returns:
        Validation results
    """
    # Generate ground truth
    true_preferences = np.random.randn(n_items)
    true_ranking = np.argsort(-true_preferences).tolist()
    
    # Run experiment
    session = ExperimentSession(n_items, max_trials=n_trials)
    
    for trial in range(n_trials):
        pair = session.get_next_pair()
        if pair is None:
            break
        
        i, j = pair
        
        # Simulate choice based on ground truth (with noise)
        p_i = norm.cdf((true_preferences[i] - true_preferences[j]) / noise)
        winner = i if np.random.rand() < p_i else j
        
        session.record_choice(i, j, winner)
    
    # Get results
    results = session.get_results()
    recovered_ranking = results['ranking']
    
    # Calculate correlation
    from scipy.stats import spearmanr
    correlation, p_value = spearmanr(true_ranking, recovered_ranking)
    
    # Calculate pairwise accuracy
    correct_pairs = 0
    total_pairs = 0
    for i in range(n_items):
        for j in range(i + 1, n_items):
            total_pairs += 1
            true_i_better = true_preferences[i] > true_preferences[j]
            recovered_i_better = results['preferences'][i] > results['preferences'][j]
            if true_i_better == recovered_i_better:
                correct_pairs += 1
    
    pairwise_accuracy = correct_pairs / total_pairs
    
    return {
        'true_ranking': true_ranking,
        'recovered_ranking': recovered_ranking,
        'correlation': correlation,
        'p_value': p_value,
        'pairwise_accuracy': pairwise_accuracy,
        'trials_used': results['trials_completed'],
        'converged': results['converged']
    }


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(level=logging.INFO, 
                       format='%(levelname)s: %(message)s')
    
    print("=" * 60)
    print("Bayesian Adaptive Preference Testing Algorithm")
    print("=" * 60)
    
    # Run validation
    print("\n🧪 Validating algorithm with ground truth...")
    results = validate_algorithm_with_ground_truth(n_items=10, n_trials=50)
    
    print(f"\n✅ Validation Results:")
    print(f"   Correlation: {results['correlation']:.3f} (p={results['p_value']:.4f})")
    print(f"   Pairwise accuracy: {results['pairwise_accuracy']:.1%}")
    print(f"   Trials used: {results['trials_used']}")
    print(f"   Converged: {results['converged']}")
    
    if results['correlation'] > 0.8:
        print("\n✅ Algorithm is working correctly!")
    else:
        print("\n⚠️  Algorithm may need tuning")
    
    # Example usage
    print("\n" + "=" * 60)
    print("Example Session")
    print("=" * 60)
    
    session = ExperimentSession(n_items=5, max_trials=15)
    
    for trial in range(15):
        pair = session.get_next_pair()
        if pair is None:
            break
        
        i, j = pair
        print(f"\nTrial {trial + 1}: Compare items {i} and {j}")
        
        # Simulate choice (random for demo)
        winner = np.random.choice([i, j])
        print(f"   → User chose item {winner}")
        
        session.record_choice(i, j, winner, response_time_ms=1500)
    
    results = session.get_results()
    print(f"\n📊 Final Results:")
    print(f"   Ranking: {results['ranking']}")
    print(f"   Preferences: {[f'{p:.2f}' for p in results['preferences']]}")
    print(f"   Trials: {results['trials_completed']}")
    print(f"   Converged: {results['converged']}")


