"""
Alternative AI Insights Test - Direct OpenAI API
Use this if GitHub Models API access is not yet available
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

def test_openai_direct():
    """Test using direct OpenAI API"""
    print("=" * 80)
    print("TESTING DIRECT OPENAI API")
    print("=" * 80)
    print()
    
    # Check for OpenAI API key
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        print("❌ OPENAI_API_KEY not found in .env file")
        print()
        print("To use direct OpenAI API:")
        print("1. Get API key from: https://platform.openai.com/api-keys")
        print("2. Add to .env: OPENAI_API_KEY=sk-your_key_here")
        print("3. Run this script again")
        print()
        return False
    
    print(f"✓ OpenAI API Key found: {openai_key[:10]}...{openai_key[-5:]}")
    print()
    
    try:
        # Initialize standard OpenAI client
        client = OpenAI(api_key=openai_key)
        print("✓ OpenAI client initialized")
        print()
        
        # Test with sample report data
        print("Generating AI insights for sample report...")
        print()
        
        sample_data = {
            'overall_coverage': 87.5,
            'pass_ratio': 92.3,
            'total_executed': 5234,
            'total_failed': 403,
            'bugs_on_dev': 12,
            'bugs_on_qa': 8,
            'critical_failures': 3,
        }
        
        prompt = f"""
Analyze this weekly DefensePro release test report:

METRICS:
- Test Coverage: {sample_data['overall_coverage']:.1f}%
- Pass Ratio: {sample_data['pass_ratio']:.1f}%
- Tests Executed: {sample_data['total_executed']:,}
- Failed Tests: {sample_data['total_failed']:,}
- Bugs in Dev: {sample_data['bugs_on_dev']}
- Bugs in QA: {sample_data['bugs_on_qa']}
- Critical Failures: {sample_data['critical_failures']}

Provide 4 actionable insights focusing on risks, trends, and recommendations.
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Cost-effective for reports
            messages=[
                {"role": "system", "content": "You are a QA expert analyzing test reports."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        insights = response.choices[0].message.content
        
        print("✓ AI INSIGHTS GENERATED:")
        print("-" * 80)
        print(insights)
        print("-" * 80)
        print()
        
        # Show cost estimate
        if hasattr(response, 'usage'):
            tokens = response.usage.total_tokens
            cost = (tokens / 1000000) * 0.15  # GPT-4o-mini pricing
            print(f"Token Usage: {tokens} tokens")
            print(f"Estimated Cost: ${cost:.4f}")
            print()
        
        print("✅ SUCCESS! OpenAI API is working correctly.")
        print()
        print("Next steps:")
        print("1. Integrate into unified_weekly_report.py")
        print("2. Cost per report: ~$0.001-0.01 (very affordable)")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Request failed: {e}")
        print()
        return False


def main():
    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  ALTERNATIVE AI INSIGHTS TEST".center(78) + "║")
    print("║" + "  Direct OpenAI API Integration".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    
    test_openai_direct()


if __name__ == "__main__":
    main()
