# bet_outlier_system.py
"""
🏈 BET OUTLIER SYSTEM
Advanced Player Props Research with Defense Analysis and Parlay Builder
"""

import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict

class BetOutlierSystem:
    def __init__(self):
        self.config = {
            'sportsdataio': {
                'base_url': 'https://api.sportsdata.io/v3/nfl',
                'key': 'e6a17abcb3d449089ddc5dcf1f0390d9'
            }
        }
        
        self.defense_rankings = {
            'KC': {'passing': 25, 'rushing': 12, 'receiving': 18},
            'BUF': {'passing': 8, 'rushing': 5, 'receiving': 10},
            'SF': {'passing': 3, 'rushing': 2, 'receiving': 4},
            'PHI': {'passing': 15, 'rushing': 8, 'receiving': 12},
            'DAL': {'passing': 6, 'rushing': 10, 'receiving': 7}
        }
        
        self.betting_odds = {
            'Patrick Mahomes': {
                'passing_yards': {'line': 275.5, 'over_odds': -115, 'under_odds': -105}
            },
            'Josh Allen': {
                'passing_yards': {'line': 265.5, 'over_odds': -110, 'under_odds': -110}
            },
            'Christian McCaffrey': {
                'rushing_yards': {'line': 85.5, 'over_odds': -115, 'under_odds': -105}
            }
        }async def analyze_player(self, player_name: str, prop_type: str, opponent: str):
        """Complete player analysis"""
        print(f"🔍 Analyzing {player_name} vs {opponent} - {prop_type}")
        
        defense_data = self.get_defense_analysis(opponent, prop_type)
        odds_data = self.get_betting_odds(player_name, prop_type)
        projection = self.calculate_projection(player_name, defense_data, prop_type)
        
        analysis = self.find_betting_edge(player_name, prop_type, projection, odds_data, defense_data)
        return analysis

    def get_defense_analysis(self, opponent: str, prop_type: str):
        """Analyze opponent defense"""
        defense_rank = self.defense_rankings.get(opponent, {}).get(self.map_prop_to_defense(prop_type), 16)
        defense_advantage = (33 - defense_rank) / 32
        
        return {
            'defense_rank': defense_rank,
            'matchup_rating': 'Favorable' if defense_advantage > 0.7 else 'Neutral'
        }

    def get_betting_odds(self, player_name: str, prop_type: str):
        """Get betting odds"""
        return self.betting_odds.get(player_name, {}).get(prop_type, {'line': 0, 'over_odds': -110, 'under_odds': -110})

    def calculate_projection(self, player_name: str, defense_data: Dict, prop_type: str):
        """Calculate projected performance"""
        base_projection = {
            'Patrick Mahomes': {'passing_yards': 285},
            'Josh Allen': {'passing_yards': 270},
            'Christian McCaffrey': {'rushing_yards': 95}
        }.get(player_name, {}).get(prop_type, 0)
        
        # Adjust for defense
        defense_adjustment = (1 - defense_data['defense_rank']/32) * 0.2
        return base_projection * (1 + defense_def find_betting_edge(self, player_name, prop_type, projection, odds, defense_data):
        """Find betting edge"""
        line = odds['line']
        edge = projection - line
        edge_percentage = (abs(edge) / line) * 100
        
        recommendation = 'OVER' if edge > 0 else 'UNDER'
        confidence = 80 if edge_percentage > 3 else 60
        
        return {
            'player': player_name,
            'prop_type': prop_type,
            'recommendation': recommendation,
            'edge_percentage': round(edge_percentage, 1),
            'projected_value': round(projection, 1),
            'market_line': line,
            'confidence_score': confidence,
            'defense_matchup': defense_data['matchup_rating'],
            'best_odds': odds['over_odds'] if recommendation == 'OVER' else odds['under_odds']
        }

    def map_prop_to_defense(self, prop_type: str):
        """Map prop type to defense category"""
        return 'passing' if 'passing' in prop_type else 'rushing'

# MAIN FUNCTION TO RUN ANALYSIS
async def main():
    system = BetOutlierSystem()
    
    print("🎯 BET OUTLIER ANALYSIS RESULTS:")
    print("=" * 40)
    
    analyses = []
    matchups = [
        ('Patrick Mahomes', 'passing_yards', 'BUF'),
        ('Josh Allen', 'passing_yards', 'KC'),
        ('Christian McCaffrey', 'rushing_yards', 'DAL')
    ]
    
    for player, prop, opponent in matchups:
        analysis = await system.analyze_player(player, prop, opponent)
        analyses.append(analysis)
        
        print(f"🏈 {analysis['player']}")
        print(f"   Prop: {analysis['prop_type']}")
        print(f"   Recommendation: {analysis['recommendation']}")
        print(f"   Projected: {analysis['projected_value']} vs Line: {analysis['market_line']}")
        print(f"   Edge: {analysis['edge_percentage']}% | Confidence: {analysis['confidence_score']}%")
        print(f"   Defense: {analysis['defense_matchup']} | Best Odds: {analysis['best_odds']}")
        print()

if __name__ == "__main__":
    asyncio.run(main())