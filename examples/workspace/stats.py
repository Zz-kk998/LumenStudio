"""计算均值的示例，故意保留一处 bug 供演示智能体修复。"""

def mean(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
