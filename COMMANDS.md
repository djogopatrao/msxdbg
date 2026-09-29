# msxdbg — Referência de comandos e sintaxe

Este documento complementa [SPEC.md](SPEC.md) e [ARCHITECTURE.md](ARCHITECTURE.md). Descreve a interface legada documentada e o contrato proposto para a reescrita. Não há implementação neste diretório para verificar a aceitação efetiva dos comandos.

**Status da sintaxe:** sem indicação especial, a forma vem da SPEC e deve ser preservada. **Proposta** identifica alterações da arquitetura ainda não implementadas. **Futuro** identifica extensões fora da primeira entrega.

## 1. Convenções

Nas sinopses, `<nome>` é um argumento obrigatório, `[argumento]` é opcional, `A | B` indica alternativas e `...` permite repetição. Esses delimitadores não são digitados. Nos exemplos de `print`, colchetes e parênteses são caracteres literais da expressão.

- Comandos e aliases são apresentados em minúsculas; não se presume aceitação de outras capitalizações.
- Registradores aceitam maiúsculas ou minúsculas. Nomes de símbolos e tipos preservam a capitalização.
- Linhas de fonte começam em 1; frames começam em 0; breakpoints recebem números locais a partir de 1.
- Endereços Z80 estão entre `0x0000` e `0xFFFF`. Alvos de execução aceitam decimal ou hexadecimal com `0x`.
- `#ABCD` é um literal hexadecimal de **expressões**; sua aceitação não é definida para alvos de `break`, `until` ou `resolve`.
- Os exemplos pressupõem que os arquivos, símbolos e tipos citados existem no projeto.
- No terminal do sistema, use aspas em caminhos com espaços e em cada argumento de `-c`. Não há sintaxe de scripts com `;`, pipes ou expansão de shell definida para o REPL.

## 2. Linha de comando do sistema

### `resolve`: consulta offline

Implementado no incremento offline: `python -m msxdbg resolve` e `python -m msxdbg --version`.
Os demais subcomandos e o manifesto ainda não estão disponíveis. `resolve` aceita também
`image::0xADDR` ou `image::arquivo:linha`; os ids são o nome de cada diretório `--out`,
ou seu path absoluto quando os nomes dos diretórios colidem. Ambiguidades mostram
os ids candidatos. Overrides `--map` só são aceitos com um único `--out`.

```text
msxdbg resolve --out <DIR> [--out <DIR> ...] [--map <FILE> ...] <ALVO>
```

Resolve um endereço hexadecimal `0xADDR` ou `arquivo.c:linha`, sem conexão ao emulador. A sinopse legada não garante nomes de símbolos como argumento de `resolve`; a resolução de símbolos em `break` não deve ser confundida com essa interface.

```sh
msxdbg resolve --out out 0x9975
msxdbg resolve --out out civ_font.c:603
msxdbg resolve --out resident/out --out dll/out libs/civ_font.c:603
```

Saída típica:

```text
0x9975  civ_font (+0x0822)  ./libs/civ_font.c:603: if ( fontId == FONT_ID_SMALL ...
```

Em falha, escreve `unresolved: <alvo>` em stderr e retorna código 1. Na reescrita, múltiplos candidatos serão reportados como ambiguidade, sem selecionar silenciosamente a primeira imagem.

### `shell`: sessão interativa

```text
msxdbg shell --out <DIR> [--out <DIR> ...]
             [--map <FILE> ...] [--cdb <FILE> ...]
             [--socket <PATH>] [--source-root <DIR>]
             [--verify-signature <ADDR=HEXBYTES>]
             [--mode c|asm] [--struct-header <FILE> ...]
```

Conecta a um openMSX já em execução e abre o prompt `(msxdbg)`. Nunca inicia o emulador, insere mídia ou altera sua velocidade.

| Opção | Significado |
| --- | --- |
| `--out DIR` | Obrigatória na interface legada; repetível, uma por imagem ligada independentemente. Descobre `.lst`, `.map` e `.cdb` |
| `--map FILE` | Override da descoberta de maps; repetível |
| `--cdb FILE` | Override de CDBs; repetível no `shell`; informações de locais e frames dependem de debug info |
| `--socket PATH` | Socket explícito; sem ele, usa o mais recente por mtime em `/tmp/openmsx-*/socket.*` |
| `--source-root DIR` | Raiz para localizar arquivos de código-fonte |
| `--verify-signature ADDR=HEXBYTES` | Endereço e sequência hexadecimal contígua de bytes esperados; exemplo `0x0100=C31101` |
| `--mode c` / `--mode asm` | Granularidade inicial de stepping e apresentação; aliases `source`/`assembly` são documentados apenas no comando interativo |
| `--struct-header FILE` | Header de tipos para `print`; repetível; não segue `#include` automaticamente. Na reescrita também fornece macros com contexto demonstrável (F18) |

```sh
msxdbg shell --out out --source-root . --mode c
msxdbg shell --out out --cdb out/game.cdb --struct-header include/types.h
msxdbg shell --out out --verify-signature 0x0100=C31101
```

Enquanto a assinatura não tiver sido observada, a parada é apresentada como possivelmente anterior ao carregamento. O usuário continua manualmente. **Proposta:** reset/load rearmam a verificação.

**Limitação legada:** overrides `--map`/`--cdb` são aplicados a todos os `--out`, e só o primeiro CDB de cada imagem é usado. **Proposta:** rejeitar overrides ambíguos com múltiplas imagens e usar associação explícita por manifesto.

### Projeto explícito — proposta

```text
msxdbg resolve --project <FILE> <ALVO>
msxdbg shell --project <FILE> [OPÇÕES_DE_SESSÃO]
msxdbg exec --project <FILE> -c <COMANDO> [-c <COMANDO> ...] --json
```

`--project` substitui a configuração por `--out` e aponta para um manifesto JSON versionado com imagens, seus ids, diretórios, maps e CDBs. Caminhos relativos são resolvidos em relação ao manifesto. O esquema exato e as regras de combinação de overrides ainda serão definidos; não há formato de manifesto estável para copiar neste momento.

### `exec`: comandos para agentes — proposta

```text
msxdbg exec --out <DIR> [--out <DIR> ...]
            [OPÇÕES_DE_SESSÃO]
            -c <COMANDO> [-c <COMANDO> ...] --json [--timeout SEGUNDOS]
```

Usa os mesmos casos de uso da sessão interativa. As opções de sessão são as de conexão, fontes, assinatura, modo e tipos descritas para `shell`; a associação de artefatos segue as mesmas regras multi-imagem propostas.

```sh
msxdbg exec --out out -c 'break main.c:42' -c 'continue' -c 'info locals' --json
```

- Executa os comandos em ordem e para no primeiro erro.
- Emite um objeto JSON por comando executado, separado por newline, em stdout; diagnósticos adicionais vão para stderr.
- Recusa `reset` e `load`, inclusive `reset yes` e `load yes`.
- Remove os breakpoints próprios ao encerrar, com relato de eventual falha de limpeza.
- `--timeout` define o prazo total do lote em segundos positivos; o padrão é 30 segundos. Ao expirar, o lote termina com erro operacional.
- `clear` é recusado no lote com `command-not-available-in-batch`, sem efeito no terminal. `reset` e `load` recebem a mesma recusa, inclusive com confirmação literal.

Envelope de exemplo:

```json
{"schema_version":1,"command_index":0,"command":"where","ok":true,"data":{"stop_id":3,"pc":39285,"location":null,"reason":"unknown"},"warnings":[],"error":null}
```

Códigos de saída propostos: `0` para sucesso, `1` para falha operacional ou de resolução, `2` para uso inválido. Comandos não executados não geram envelopes de sucesso.

O envelope JSON v1 contém sempre `schema_version`, `command_index`, `command`, `ok`, `data`, `warnings` e `error`. Em sucesso, `error` é `null`; em falha, `data` é `null`. Endereços e valores são números JSON, bytes são strings hexadecimais minúsculas e enums usam seus valores textuais estáveis. Campos internos nunca são serializados implicitamente. Erro ou pendência na limpeza transforma um status que seria 0 em 1.

### Versão

```sh
msxdbg --version
```

## 3. Alvos de breakpoints e execução

```text
ALVO := ENDEREÇO | SÍMBOLO | ARQUIVO:LINHA
```

| Forma | Exemplo | Interpretação |
| --- | --- | --- |
| Decimal | `256` | Endereço 0x0100 |
| Hexadecimal | `0x9975` | Endereço do barramento Z80 |
| Símbolo MAP | `_Map_GetTile` | Endereço do símbolo exato |
| Arquivo e linha | `libs/civ_font.c:603` | Instrução associada à linha |

Uma linha sem código avança para a próxima linha com código no mesmo arquivo e produz uma nota. Um endereço numérico pode ser usado mesmo sem fonte correspondente, por exemplo na BIOS.

**Propostas para a reescrita:** aceitar o nome C `Map_GetTile`, qualificar como `resident::Map_GetTile` ou `dll::libs/civ_font.c:603`, comparar componentes completos do caminho e reportar ambiguidades. `map.c` não deve corresponder a `worldmap.c`. A qualificação também será usada nas consultas offline quando aplicável; não implica suporte geral a `::` dentro de expressões aritméticas.

Os breakpoints continuam sendo por endereço. `dll::funcao` escolhe qual símbolo resolver, mas não condiciona o disparo a um segmento de mapper.

## 4. Breakpoints

| Sintaxe | Aliases | Efeito |
| --- | --- | --- |
| `break <ALVO>` | `b` | Cria breakpoint e informa número local e localização |
| `delete <N>` | `d` | Remove o breakpoint N no emulador antes de removê-lo localmente |
| `suspend <N>` | `disable` | Desativa N, preservando número e localização; operação idempotente |
| `resume <N>` | `enable` | Reativa N no mesmo endereço e sob o mesmo número; operação idempotente |

```text
break _Map_GetTile
b civ_font.c:603
break 0x9975
info breakpoints
disable 2
enable 2
delete 2
```

`N` é o número local, não o identificador openMSX como `bp#3`. Números não são reutilizados na sessão. Não estão definidas formas para excluir todos, intervalos de números ou condições.

## 5. Controle de execução

| Sintaxe | Aliases | Efeito |
| --- | --- | --- |
| `continue` | `c` | Retoma execução e espera uma parada |
| `step` | `s` | Em modo C, entra em chamadas até mudar de linha; em asm, executa um passo de instrução |
| `next` | `n` | Como step, mas usa step-over para passar sobre chamadas |
| `stepi` | `si` | Executa uma instrução com step-into e apresenta a parada em asm |
| `finish` | — | Executa até sair da função corrente |
| `until <ALVO>` | `advance` | Executa até o endereço resolvido ou outra parada |
| `where` | — | Exibe novamente a localização do PC atual |

Esses comandos não aceitam contagem de passos. `until` exige alvo; não é a variante sem argumentos de outros depuradores. `where` mostra a parada atual; para pilha, use `backtrace`.

```text
b main.c:42
c
s
n
si
until _UpdateWorld
finish
where
```

O step por linha também termina em localização desconhecida, breakpoint ativo, interrupção ou limite de 20.000 iterações. Ctrl-C durante a espera solicita interrupção da execução.

**Diferença proposta:** `finish` aguardará parada confirmada; o legado reporta imediatamente após `step_out`. Inspeções na reescrita exigem estado parado conhecido. Cada nova parada seleciona novamente o frame 0.

## 6. Código-fonte e disassembly

### `list` — alias `l`

```text
list
list <LINHA>
list <ARQUIVO>:<LINHA>
list next
list previous
```

Mostra 11 linhas em torno do alvo; sem argumento, usa o PC. Uma linha sem arquivo usa o contexto de fonte corrente. `next`/`previous` navegam na listagem; `>` marca a linha do PC.

```text
list
l 603
list libs/civ_font.c:603
list next
list previous
```

Busca fontes pelo caminho absoluto, por `--source-root` ou pelo diretório pai de cada diretório de listings. Sem acesso ao arquivo, o relatório de parada pode usar o texto disponível no `.lst`.

### `disassemble` — alias `disas`

```text
disassemble
disassemble <ENDEREÇO> [CONTAGEM]
disassemble next
disassemble previous
```

Por padrão, mostra 10 instruções a partir do PC. O argumento único numérico é endereço, não contagem. `next`/`previous` navegam pelo disassembly; a navegação anterior é aproximada devido ao tamanho variável das instruções Z80.

```text
disas
disas 0x9975 20
disas next
disas previous
```

**Proposta:** aceitar símbolos pelo resolvedor de alvos, por exemplo `disas Map_GetTile 20`. No legado, nomes de símbolos nessa posição falham.

## 7. Pilha e frames

| Sintaxe | Alias | Efeito |
| --- | --- | --- |
| `backtrace` | `bt` | Mostra a cadeia de chamadas, até 64 frames |
| `frame` | — | Mostra o frame selecionado |
| `frame <N>` | — | Seleciona um frame existente para variáveis locais e parâmetros |

```text
bt
frame 1
info args
info locals
print count
frame 0
```

O backtrace depende de `.cdb` e da cadeia de IX reconhecida. A caminhada termina com motivo explícito quando não pode prosseguir. Frames de chamadores não permitem recuperar variáveis residentes em registradores. `frame` não altera PC nem execução; somente o contexto de inspeção. Registradores solicitados diretamente continuam sendo os registradores vivos, não um conjunto reconstruído do chamador.

## 8. `print`: memória, registradores e variáveis

Aliases: `p` e `?`.

```text
print <EXPRESSÃO> [TIPO]
p <EXPRESSÃO> [TIPO]
? <EXPRESSÃO> [TIPO]
```

**Proposta preferida:** `print/TIPO EXPRESSÃO`, por exemplo `print/u16 hl + 3`. A aceitação do sufixo `/TIPO` nos aliases ainda não foi especificada; use `print/TIPO`.

No legado, a expressão deve caber em um token sem espaços, pois o segundo token é interpretado como tipo. Na reescrita, espaços serão aceitos e o tipo final permanecerá compatível quando não houver ambiguidade. A forma com `/TIPO` evita essa ambiguidade.

### Gramática aritmética legada (referência histórica)

Esta subseção e seus exemplos descrevem v1.2c0. Para implementar ou usar a reescrita, prevalece a subseção “Extensão planejada: calculadora e macros (F17/F18)” abaixo.

Aqui as aspas identificam caracteres literais da linguagem, e não aspas a serem digitadas:

```text
target := '[' expr ']' | '(' expr ')' | ident '[' expr ']' | expr
expr   := term (('+' | '-') term)*
term   := factor (('*' | '/') factor)*
factor := ('+' | '-') factor | '(' expr ')' | atom
atom   := register | number | map_symbol
number := '#' HEX | '0x' HEX | DECIMAL
```

Multiplicação/divisão precedem soma/subtração. Divisão inteira trunca em direção a zero; divisão por zero falha. O endereço final é mascarado para 16 bits. Não há operadores de comparação, bitwise, atribuição ou chamada de função nessa gramática.

| Exemplo | Significado |
| --- | --- |
| `print hl` | Valor de HL, salvo se houver variável CDB com esse nome no contexto |
| `print [hl] u16` | Lê dois bytes no endereço contido em HL |
| `print (hl) u16` | Forma indireta legada equivalente |
| `print hl+3 u8` | Lê um byte no endereço HL+3 |
| `print 0xC000 u16` | Lê memória em 0xC000; não imprime o literal como cálculo |
| `print #C000 u8` | Literal hexadecimal alternativo dentro de expressão |
| `print _counter` | Lê um byte no endereço do símbolo MAP por padrão |
| `print _tiles[3] u16` | Lê elemento em `_tiles + 3 * 2`; base MAP e tipo explícito |
| `print count` | Se não for resolvido pela expressão/MAP, procura variável CDB no frame selecionado |
| `print _player Player` | Lê e apresenta uma struct cujo tipo foi carregado |
| `print/u16 hl + 3` | **Proposta:** formato explícito e expressão com espaços |

Uma expressão numérica representa endereço de leitura. Não existe, na interface legada, comando geral para imprimir apenas o resultado aritmético sem acessar memória. Um registrador isolado é a exceção: apresenta seu valor, ignorando um tipo fornecido com aviso.

Parênteses externos completos mantêm a forma indireta legada. **Correção proposta:** `(hl+3)*(hl)` deve ser analisada inteira; o parser não pode remover o primeiro e o último parêntese como se envolvessem toda a expressão.

### Extensão planejada: calculadora e macros (F17/F18)

As regras abaixo substituem, na reescrita, a interpretação legada de toda expressão numérica como endereço. Ainda não estão implementadas. Os exemplos e a gramática anteriores descrevem o legado; esta seção define a extensão solicitada.

| Forma | Resultado planejado |
| --- | --- |
| `print 2 + 3 * 4` | Valor 14; nenhuma leitura de memória |
| `print (2 + 3) * 4` | Valor 20; parênteses agrupam |
| `print 65535 + 1` | Valor 65536, sem truncamento |
| `print hex(255)` | `0xff` |
| `print bin(10)` | `0b1010` |
| `print hex(-10)` | `-0xa`, sem largura implícita |
| `print hex(bin(10) + 1)` | `0xb`; o inteiro é preservado pelas funções de apresentação |
| `print [0x8000+MY_OFFSET] u16` | Expande a macro e lê u16 no endereço calculado |
| `print NLV( _g_teste,_g_outro_teste)` | Expande NLV carregada do projeto e avalia a expressão resultante |
| `print 0xC000 u16` | Mantém leitura legada por tipo explícito |
| `print/u16 hl + 3` | Mantém leitura legada por formato/tipo explícito |
| `print (hl)` | Valor de HL; para ler memória, migrar para `print [hl]` |

Regras de seleção, aplicadas após expansão de macros:

1. Colchetes envolvendo o alvo inteiro solicitam leitura de memória; tipo padrão u8.
2. Tipo explícito mantém as formas de leitura legadas, incluindo indexação MAP e variáveis. Um registrador isolado mantém seu comportamento legado. Não combinar tipo de memória com uma função externa hex/bin: essa mistura é rejeitada com orientação para separar leitura e apresentação.
3. Identificador isolado de variável CDB ou símbolo MAP mantém a impressão legada da variável/memória. Macro constante expandida para número produz cálculo.
4. As demais expressões sem tipo calculam valores. Em aritmética, símbolo MAP fornece endereço; variável CDB tipada fornece valor; registrador fornece valor. Não inferir dereferência de um número.

`hex(expr)` e `bin(expr)` recebem exatamente um inteiro e determinam formato somente quando forem a chamada externa do resultado. Internamente preservam o número: `hex(10) + 1` calcula 11 com apresentação padrão. Não são conversões para string e não executam funções do programa. Resultados JSON mantêm o número e registram a base de apresentação.

A gramática de cálculo amplia `atom` com chamadas e vírgulas:

```text
atom      := register | number | identifier | call
call      := identifier '(' [expr (',' expr)*] ')'
```

Essa produção é esquemática: macros são reconhecidas/expandidas sobre tokens antes do parsing final; depois da expansão, só hex/bin permanecem como chamadas aceitas. Multiplicação, divisão e sinais mantêm as regras anteriores; não há chamada genérica de C. Tipos/operadores futuros de F06 são necessários quando o corpo da macro os usa.

Por exemplo, as definições de teste:

```c
#define MY_OFFSET 0x20
#define NLV(a,b) ((a)+(b))
```

fazem o primeiro pedido ler em 0x8020 e o segundo somar os endereços MAP de `_g_teste` e `_g_outro_teste`. A definição de NLV é ilustrativa: seu significado real vem do projeto.

Definições carregadas de fontes/headers conhecidos conservam imagem, unidade de compilação, arquivo e linha. Headers fornecidos por `--struct-header` também podem fornecer macros. Inclusões, condicionais e flags exigem contexto conhecido; não se presume pré-processamento C completo. Macros ausentes, ambíguas, recursivas, com aridade incorreta ou recursos não suportados produzem diagnóstico. A primeira etapa não suporta `#`, `##` nem macros variádicas. `hex`/`bin` são nomes reservados; conflito de macro é informado.

Cálculos constantes não consultam o emulador. Referências a estado vivo exigem inspeção válida. O catálogo e a expansão nunca executam scripts, funções do programa ou ferramentas externas implicitamente. Requisitos completos e testes: [BACKLOG.md, F17/F18](BACKLOG.md).

### Registradores aceitos

```text
PC SP AF BC DE HL IX IY AF2 BC2 DE2 HL2 I R IM IFF
A F B C D E H L
A2 F2 B2 C2 D2 E2 H2 L2
IXH IXL IYH IYL PCH PCL SPH SPL
```

Os registradores de 8 bits derivados são calculados a partir dos pares. Nas expressões, nomes de registradores têm precedência sobre símbolos MAP. Para um identificador isolado de `print`, uma variável CDB homônima pode ter precedência, conforme a resolução legada.

### Tipos e formatos

| Tipo | Aliases | Bytes | Apresentação |
| --- | --- | --- | --- |
| `u8` | `b` | 1 | Inteiro sem sinal, decimal e hexadecimal; padrão para endereço/MAP |
| `i8` | `s8` | 1 | Inteiro com sinal e hexadecimal bruto |
| `u16` | `word` | 2 | Inteiro sem sinal |
| `i16` | `s16` | 2 | Inteiro com sinal |
| `u32` | `dword` | 4 | Inteiro sem sinal |
| `i32` | `s32` | 4 | Inteiro com sinal |
| `u64` | — | 8 | Inteiro sem sinal |
| `i64` | `s64` | 8 | Inteiro com sinal |
| `f32` | `float` | 4 | IEEE-754; a correspondência com o ABI SDCC Z80 ainda exige validação |
| `bool` | — | 1 | Booleano e byte bruto |
| `char` | `c` | 1 | Caractere, decimal e hexadecimal; escape para não imprimíveis |
| `c8` | — | 1 | Mesmo formato de caractere |
| `c16` | — | 2 | Formato numérico |
| `ptr` | — | 2 | Endereço hexadecimal |
| `str` | `cstr` | Até 256 | Texto Latin-1 até NUL; indica truncamento |
| Nome de struct | — | Calculado | Campos e structs aninhadas; arrays mostram até 16 elementos |

Valores multibyte usam little-endian. Structs dependem de layout conhecido; headers legados aceitam um subconjunto de `typedef struct`, sem ponteiros declarados em campos, bitfields ou unions embutidas. Falhas de um tipo são relatadas sem descartar os demais.

Variáveis CDB escalares podem inferir tipo pelo tamanho e sinal. Ponteiros, arrays e structs não recebem um tipo padrão adivinhado em `print`; forneça um tipo. Variáveis em registradores têm confiabilidade limitada pela ausência de live ranges; struct em registradores é recusada. Valores otimizados ou sem localização demonstrável são apresentados como indisponíveis.

### Expressões tipadas futuras

| Forma | Intenção |
| --- | --- |
| `*p` | Desreferenciar ponteiro tipado |
| `&x` | Obter endereço de variável |
| `a[i]` | Indexar usando o tipo CDB, ampliando a forma MAP já existente |
| `s.f` | Consultar campo de struct |
| `p->f` | Consultar campo por ponteiro |

Essas formas dependem da segunda etapa do avaliador. Não devem ser tratadas como aceitas pelo legado. Casts C como `print (u16)expr` não foram escolhidos como sintaxe da primeira versão.

## 9. `info`: consultas do estado

| Sintaxe | Aliases do subcomando | Conteúdo |
| --- | --- | --- |
| `info registers` | `reg`, `regs` | Registradores principais em hexadecimal e decimal |
| `info breakpoints` | `break`, `b` | Número, endereço, localização e estado dos breakpoints |
| `info pages` | `page`, `slots`, `segments` | Quatro páginas da CPU, slots e segmentos do mapper |
| `info symbol <EXPRESSÃO>` | `sym` | Símbolo público mais próximo do endereço avaliado e offset |
| `info page3` | `free` | Dados estáticos, heap, espaço livre, pilha e reserva DOS |
| `info locals` | `local` | Variáveis locais em escopo no frame selecionado |
| `info args` | `arguments` | Parâmetros do frame selecionado |

```text
info regs
info b
info slots
info symbol hl+3
info free
info local
info arguments
```

`info symbol` avalia um endereço, sem a leitura de valor feita por `print`. No legado, só o primeiro token da expressão é usado; **proposta:** aceitar a expressão completa, como `info symbol hl + 3`.

`info locals` e `info args` exigem CDB e exibem nome, localização e valor; ponteiros simples de dois bytes são mostrados como `u16`, outros compostos podem aparecer como bytes brutos. Não alteram o frame selecionado.

O relatório `page3` depende de símbolos e limites de memória do programa. **Proposta:** regiões sem evidência aparecem como desconhecidas. Heap alcançando ou ultrapassando SP gera aviso de possível corrupção.

## 10. Modo, savestate e sessão

| Sintaxe | Aliases | Efeito |
| --- | --- | --- |
| `mode` | — | Mostra modo atual |
| `mode c` | `mode source` | Stepping e relatórios orientados a linhas C |
| `mode asm` | `mode assembly` | Stepping e relatórios orientados a instruções |
| `save` | — | Salva estado sob o nome interno `msxdbg_<pid>`; não recebe nome |
| `reset` | — | Explica a confirmação necessária, sem resetar |
| `reset yes` | — | Solicita soft reset; exige digitação humana a cada operação |
| `load` | — | Explica a confirmação necessária, sem restaurar |
| `load yes` | — | Restaura o savestate da sessão; exige digitação humana a cada operação |
| `clear` | Ctrl-L | Limpa tela e scrollback |
| `help` | — | Mostra ajuda dos comandos |
| `quit` | `q`, `exit` | Encerra a sessão; EOF também encerra |

Sem savestate disponível, `load yes` orienta executar `save` primeiro. Não há argumentos para escolher nome/arquivo de estado, nem `--force`. Reset/load nunca são executados por repetição de linha vazia ou por fluxos automatizados.

**Proposta:** quit/EOF tentam remover os breakpoints criados pela sessão e relatam falhas. O legado os deixa no emulador. Nenhuma saída da sessão implica reset ou reinício do emulador.

## 11. Interação no REPL

- Enter em linha vazia repete o último comando repetível. Reset/load nunca entram nesse mecanismo.
- Tab completa comandos e, conforme o contexto, fontes, símbolos, registradores, tipos e subcomandos de `info`. Na reescrita, inclui macros resolvíveis no contexto e hex/bin, sem consultar o alvo.
- O histórico é mantido em memória.
- Ctrl-C no prompt é ignorado; durante execução/stepping, interrompe a espera e solicita parada.
- Erros de comandos são apresentados sem encerrar o REPL.
- **Proposta:** ajuda e completion derivam do mesmo registro, incluindo todos os aliases documentados.

## 12. Fora da sintaxe da primeira versão

Os requisitos de evolução estão detalhados em [BACKLOG.md](BACKLOG.md), com prioridade, dependências e critérios de aceitação. A inclusão no backlog não torna uma sintaxe disponível:

| Funcionalidade | Requisito | Situação |
| --- | --- | --- |
| Escrita de memória | F14 | Adiada; comando ainda a definir |
| Escrita de registradores | F15 | Adiada; comando ainda a definir |
| Watchpoints | F10 | Adiados; modos de acesso, faixa e comandos serão especificados |
| Condições de breakpoint | F08 | Adiadas; predicados tipados, sem Tcl arbitrário |
| Breakpoints por slot/mapper | F09 | Adiados; distintos da qualificação de nome por imagem |
| Seleção de imagem pelo mapper ativo | F13 | Investigação; exige associação explícita de imagem e mapeamento |
| `continue --until-signature` | F07 | Forma proposta; execução explícita com limites, fora do contrato inicial |
| Gerenciamento de mídia, boot ou velocidade | X01 | Excluído pelo escopo attach-only |
| Inicialização ou encerramento do emulador | X02 | Excluído; o debugger conecta a um processo existente |

Gerenciamento de mídia e ciclo de vida do emulador são restrições de escopo, não funcionalidades apenas adiadas. Reset/load mantêm as confirmações humanas documentadas e não podem ser automatizados.

A especificação introdutória menciona 25 comandos, mas sua tabela enumera 24 comandos principais. Esta referência cobre os 24 efetivamente enumerados e todos os seus aliases, sem inventar um comando adicional.
