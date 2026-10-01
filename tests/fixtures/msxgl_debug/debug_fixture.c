typedef unsigned char u8;
typedef unsigned int u16;

volatile u16 g_DebugCounter = 0;
volatile u8 g_DebugDone = 0;

static u16 AddThree(u16 value)
{
	u16 local = value + 1;
	local += 2;
	return local;
}

static void DebugTick(void)
{
	g_DebugCounter = AddThree(g_DebugCounter);
	if (g_DebugCounter >= 12)
		g_DebugDone = 1;
}

void main(void)
{
	g_DebugCounter = 0;
	while (!g_DebugDone)
		DebugTick();

	for (;;)
	{
		g_DebugCounter++;
	}
}
