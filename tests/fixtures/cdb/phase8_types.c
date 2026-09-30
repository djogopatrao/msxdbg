/* Dedicated SDCC Z80 evidence fixture for phase 8. */
typedef struct {
    unsigned char x;
    signed int y;
} Phase8Point;

typedef struct {
    Phase8Point points[2];
    unsigned int *word_ptr;
    Phase8Point *point_ptr;
} Phase8Container;

volatile Phase8Point phase8_point = { 0x12, -0x1234 };
volatile Phase8Container phase8_container;
volatile unsigned int phase8_words[3] = { 0x1234, 0xabcd, 0x8001 };
volatile float phase8_float_zero = 0.0f;
volatile float phase8_float_one = 1.0f;
volatile float phase8_float_negative = -2.5f;

unsigned int phase8_read(Phase8Container *container, unsigned char index)
{
    return container->points[index].x + *container->word_ptr;
}
