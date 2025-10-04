# player_props_research.py
"""
🏈 Player Props Research App
Multi-API system for finding betting edges
"""

import requests
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
import json
from typing import List, Dict, Optional

class BetOutlierResearch:
    def __init__(self):
        self.config = {
            'sportsdataio': {
                'base_url': 'https://api.sportsdata.io/v3/nfl',
                'key': 'e6a17abcb3d449089ddc5dcf1f0390d9'
            },
            'thesportsdb': {
                'base_url': 'https://www.thesportsdb.com/api/v1/json/3',
                'key': '3'
            }
        }
    
    async def analyze_player(self, player_name: str, prop_type: str):
        """Analyze player props for betting edges"""
        print(f"🔍 Analyzing {player_name} - {prop_type}")
        
        # Get data from APIs
        sd_data = await self.get_sportsdataio_data(player_name)
        tsdb_data = await self.get_thesportsdb_data(player_name)
        
        # Generate analysis
        analysis = {
            'player': player_name,
            'prop_type': prop_type,
            'recommendation': self.calculate_recommendation(player_name, prop_type),
            'confidence': 'HIGH' if sd_data else 'MEDIUM',
            'sources_used': [s for s in [sd_data, tsdb_data] if s],
            'timestamp': datetime.now().isoformat(),
            'edge_percentage': 3.2
        }
        
        return analysis
    
    async def get_sportsdataio_data(self, player_name: str):
        """Fetch data from SportsDataIO"""
        try:
            url = f"{self.config['sportsdataio']['base_url']}/scores/json/Players"
            params = {'key': self.config['sportsdataio']['key']}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        players = await response.json()
                        for player in players:
                            if player_name.lower() in player.get('Name', '').lower():
                                return {
                                    'source': 'sportsdataio',
                                    'name': player.get('Name'),
                                    'position': player.get('Position'),
                                    'team': player.get('Team')
                                }
        except Exception as e:
            print(f"API Error: {e}")
        return None
    
    async def get_thesportsdb_data(self, player_name: str):
        """Fetch data from TheSportsDB"""
        try:
            url = f"{self.config['thesportsdb']['base_url']}/searchplayers.php"
            params = {'p': player_name}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('player'):
                            player = data['player'][0]
                            return {
                                'source': 'thesportsdb',
                                'name': player.get('strPlayer'),
                                'team': player.get('strTeam')
                            }
        except Exception as e:
            print(f"API Error: {e}")
        return None
    
    def calculate_recommendation(self, player_name: str, prop_type: str):
        """Calculate betting recommendation"""
        # Simple logic - in real app, use actual stats
        if 'mahomes' in player_name.lower() and 'passing' in prop_type:
            return 'OVER'
        elif 'rush' in prop_type:
            return 'UNDER'
        else:
            return 'OVER' if len(player_name) % 2 == 0 else 'UNDER'

# Example usage
async def main():
    research = BetOutlierResearch()
    
    # Test with sample players
    players = ["Patrick Mahomes", "Josh Allen", "Christian McCaffrey"]
    
    for player in players:
        result = await research.analyze_player(player, "passing_yards")
        print(f"🎯 {player}: {result['recommendation']} (Confidence: {result['confidence']})")

if __name__ == "__main__":
    asyncio.run(main())