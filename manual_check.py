import asyncio
from supportdesk.compliance import ComplianceSession
from supportdesk.orchestrate import orchestrate
from supportdesk.reviewer import review_case

MESSAGE = "The app will not open. Call me on 9876543210"

async def main():
    outcome = await orchestrate(MESSAGE, session=ComplianceSession())
    reviewed = review_case(outcome)
    result = reviewed.result
    print(reviewed.run.state.value)
    print(result.reply.text)
    print(result.routing_note.team, result.routing_note.priority.value, result.routing_note.pattern_signal.value)
    print(result.compliance.decision.value)

asyncio.run(main())