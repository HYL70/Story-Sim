"""
API 连通性测试
"""

import config
from engine import llm_client


def main():
    print("=" * 50)
    print("DeepSeek API 连通性测试")
    print("=" * 50)
    print(f"API Key: {config.DEEPSEEK_API_KEY[:10]}...{config.DEEPSEEK_API_KEY[-4:]}")
    print(f"Base URL: {config.DEEPSEEK_BASE_URL}")
    print(f"Model: {config.ACTIVE_MODEL}")
    print()

    print("正在测试连接...")
    result = llm_client.test_connection()
    if result["success"]:
        print(f"连接成功！")
        print(f"   响应: {result['message']}")
    else:
        print(f"连接失败！")
        print(f"   错误: {result['message']}")
    print()

    print("测试 JSON 模式...")
    try:
        response = llm_client.chat(
            messages=[
                {"role": "system", "content": "请用JSON格式回复"},
                {"role": "user", "content": "给我一个古代女子的名字和身份"},
            ],
            json_mode=True,
            max_tokens=100,
        )
        parsed = llm_client.parse_json_response(response)
        print(f"JSON 模式正常")
        print(f"   响应: {parsed}")
    except Exception as e:
        print(f"JSON 模式失败: {e}")


if __name__ == "__main__":
    main()
