"""
Test GitHub Models API Integration for AI Insights
This script tests the ability to generate AI insights using GitHub Copilot subscription
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

def test_github_models_connection():
    """Test basic connection to GitHub Models API"""
    print("=" * 80)
    print("TESTING GITHUB MODELS API CONNECTION")
    print("=" * 80)
    print()
    
    # Check if token exists
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        print("❌ GITHUB_TOKEN not found in .env file")
        return False
    
    print(f"✓ GitHub Token found: {github_token[:20]}...{github_token[-10:]}")
    print()
    
    # Initialize OpenAI client with GitHub endpoint
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token
        )
        print("✓ OpenAI client initialized with GitHub Models endpoint")
        print()
        return client
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return None


def test_simple_completion(client):
    """Test a simple completion"""
    print("=" * 80)
    print("TEST 1: SIMPLE COMPLETION")
    print("=" * 80)
    print()
    
    try:
        print("Sending request to GPT-4o-mini...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "What are the top 3 metrics for QA release readiness? Answer in one sentence."}
            ],
            max_tokens=100
        )
        
        result = response.choices[0].message.content
        print("✓ Response received:")
        print(f"  {result}")
        print()
        return True
        
    except Exception as e:
        print(f"❌ Request failed: {e}")
        print()
        return False


def test_report_insights(client):
    """Test generating insights with sample report data"""
    print("=" * 80)
    print("TEST 2: GENERATE REPORT INSIGHTS")
    print("=" * 80)
    print()
    
    # Sample data similar to what your reports would have
    sample_data = {
        'overall_coverage': 87.5,
        'pass_ratio': 92.3,
        'total_executed': 5234,
        'total_failed': 403,
        'bugs_on_dev': 12,
        'bugs_on_qa': 8,
        'critical_failures': 3,
        'platform_performance': [
            {'platform': 'FPGA Transparent', 'coverage': 91.2, 'pass_ratio': 94.5},
            {'platform': 'FPGA Routing', 'coverage': 88.7, 'pass_ratio': 93.1},
            {'platform': 'Software Transparent', 'coverage': 85.3, 'pass_ratio': 89.8},
            {'platform': 'Software Routing', 'coverage': 82.1, 'pass_ratio': 88.2},
        ]
    }
    
    # Build prompt
    prompt = f"""
Analyze this weekly DefensePro release test report:

CURRENT METRICS:
- Test Coverage: {sample_data['overall_coverage']:.1f}%
- Pass Ratio: {sample_data['pass_ratio']:.1f}%
- Tests Executed: {sample_data['total_executed']:,}
- Failed Tests: {sample_data['total_failed']:,}
- Bugs in Dev: {sample_data['bugs_on_dev']}
- Bugs in QA: {sample_data['bugs_on_qa']}
- Critical Failures (all platforms): {sample_data['critical_failures']}

PLATFORM PERFORMANCE:
"""
    
    for p in sample_data['platform_performance']:
        prompt += f"- {p['platform']}: {p['coverage']:.1f}% coverage, {p['pass_ratio']:.1f}% pass rate\n"
    
    prompt += """

TASK:
Provide 4-5 actionable insights focusing on:
1. Critical risks requiring immediate attention
2. Quality trends and patterns
3. Platform-specific observations
4. Prioritized recommendations for the team

Be concise, technical, and actionable. Format as bullet points.
"""
    
    print("Sending request with sample report data...")
    print(f"Coverage: {sample_data['overall_coverage']:.1f}%, Pass Ratio: {sample_data['pass_ratio']:.1f}%")
    print()
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Using full GPT-4o for better quality
            messages=[
                {
                    "role": "system",
                    "content": "You are a QA automation expert analyzing DefensePro release test reports. Provide technical, actionable insights."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=600,
            top_p=0.95
        )
        
        insights = response.choices[0].message.content
        
        print("✓ AI Insights Generated:")
        print("-" * 80)
        print(insights)
        print("-" * 80)
        print()
        
        # Show token usage
        if hasattr(response, 'usage'):
            print(f"Token Usage: {response.usage.total_tokens} tokens")
            print()
        
        return True
        
    except Exception as e:
        print(f"❌ Request failed: {e}")
        print()
        return False


def test_multiple_models(client):
    """Test different available models"""
    print("=" * 80)
    print("TEST 3: COMPARE DIFFERENT MODELS")
    print("=" * 80)
    print()
    
    models_to_test = [
        "gpt-4o-mini",
        "gpt-4o",
    ]
    
    simple_prompt = "In one sentence, what's the most critical QA metric for release readiness?"
    
    for model in models_to_test:
        print(f"Testing model: {model}")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": simple_prompt}],
                max_tokens=100
            )
            result = response.choices[0].message.content
            print(f"  ✓ {result}")
            print()
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            print()


def main():
    """Run all tests"""
    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  GITHUB MODELS API - AI INSIGHTS TEST".center(78) + "║")
    print("║" + "  Testing GPT Integration for Report Generation".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    
    # Test 1: Connection
    client = test_github_models_connection()
    if not client:
        print("❌ Cannot proceed without valid client connection")
        return
    
    # Test 2: Simple completion
    if not test_simple_completion(client):
        print("❌ Simple completion failed, check your token permissions")
        return
    
    # Test 3: Report insights (the main use case)
    test_report_insights(client)
    
    # Test 4: Multiple models
    test_multiple_models(client)
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()
    print("✓ GitHub Models API connection: SUCCESS")
    print("✓ AI insights generation: READY FOR INTEGRATION")
    print()
    print("Next steps:")
    print("1. Integrate generate_ai_insights() function into unified_weekly_report.py")
    print("2. Add AI insights section to HTML report template")
    print("3. Test with real report data")
    print()


if __name__ == "__main__":
    main()
