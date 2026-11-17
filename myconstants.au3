#include-once

Global $SEP = Opt("GUIDataSeparatorChar")

Opt("GUIOnEventMode", 1)                         ; Enable GUI OnEvent Mode globally


#include <ColorConstants.au3>


; Icon characters
Global Const $ICON_CFG = ChrW(0xE115) ; ChrW(0x2699)                        ; configuration sprocket icon
Global Const $ICON_STILL_CAMERA2 = ChrW(0xD83D) & ChrW(0xDCF7)              ; screenshot still camera icon
Global Const $ICON_STILL_CAMERA = ChrW(0xE114)                              ; screenshot still camera icon
Global Const $ICON_SCREENSHOT = $ICON_STILL_CAMERA                          ; still camera icon
Global Const $ICON_REFRESH2 = ChrW(0x27F3) ; 0x21BB							; refresh icon - circle arrow
Global Const $ICON_REFRESH = ChrW(0xE117)                                   ; refresh icon - circle arrow
Global Const $ICON_POWERBTN = ChrW(0x23FB)                                  ; power button
Global Const $ICON_DEGREE = ChrW(0x00B0)                                    ; degree superscript symbol
Global Const $ICON_DEGREEC = $ICON_DEGREE & "C" ; 0x2103					; temperature in Celsius
Global Const $ICON_DEGREEF = $ICON_DEGREE & "F" ; 0x2104					; temperature in Fahrenheit
Global Const $ICON_SEARCH = ChrW(0xE11A) ; ChrW(0x2315)                     ; search magnifying glass
Global Const $ICON_SEARCH3 = ChrW(0x2315)                                   ; search magnifying glass
Global Const $ICON_SEARCH2 = ChrW(0xD83D) & ChrW(0xDD0D) & ChrW(0xFE0E)     ; ChrW(0xD83D) & ChrW(0xDD0D)
Global Const $ICON_GLASS = ChrW(0xD83D) & ChrW(0xDD0D)
Global Const $ICON_MENU2 = ChrW(0x2630)                                     ; parallel horizontal stripes menu button
Global Const $ICON_MENU1 = ChrW(0xE169)                                     ; parallel horizontal stripes menu button
Global Const $ICON_NET = ChrW(0xD83D) & ChrW(0xDDA7)                        ; computers on a network icon
Global Const $ICON_TABS = ChrW(0xD83D) & ChrW(0xDDC2) ; 0x29C9, 0x2EB2		; tabs icon
Global Const $ICON_BOOK = ChrW(0xD83D) & ChrW(0xDD6E)                       ; book icon
Global Const $ICON_FLOPPY = ChrW(0xE105)                                    ; floppy disk icon
Global Const $ICON_FLOPPY2 = ChrW(0xD83D) & ChrW(0xDCBE) ; ChrW32(0x1F4BE)	; floppy disk icon
Global Const $ICON_FOLDER1 = ChrW(0xD83D) & ChrW(0xDCC1) ; ChrW32(0x1F4C1)	; folder icon
Global Const $ICON_FOLDER2 = ChrW32(0x1F4C2)                                ; folder icon
Global Const $ICON_FOLDERL = ChrW(0xE1C1)                                   ; folder icon with tab on the left
Global Const $ICON_FOLDERR = ChrW(0xE188)                                   ; folder icon with tab on the right
Global Const $ICON_SAVE = $ICON_FLOPPY                                      ; floppy disk icon to represent save
Global Const $ICON_OPEN = $ICON_FOLDERL                                     ; folder icon to represent open
Global Const $ICON_CHECK1 = ChrW(0xE10B)                                    ; check
Global Const $ICON_CHECK2 = ChrW(0x2713)                                    ; check
Global Const $ICON_CHECK2B = ChrW(0x2714)                                   ; check bold
Global Const $ICON_CHECK = $ICON_CHECK2                                     ; check
Global Const $ICON_INFO3 = ChrW(0xE2C0)                                     ; information icon
Global Const $ICON_INFO1 = ChrW(0x2139)                                     ; information icon
Global Const $ICON_INFO2 = ChrW32(0x1F6C8)                                  ; information icon
global const $ICON_INFO = $ICON_INFO3   									; select information icon

Global Const $ICON_NWARROW1 = ChrW(0x2196)                                  ; arrow pointing NW, up left
Global Const $ICON_NWARROW2 = ChrW32(0x1F874)                               ; arrow pointing NW, up left
Global Const $ICON_NEARROW1 = ChrW(0x2197)                                  ; arrow pointing NE, up right
Global Const $ICON_NEARROW2 = ChrW32(0x1F875)                               ; arrow pointing NE, up right
Global Const $ICON_SEARROW1 = ChrW(0x2198)                                  ; arrow pointing SE, down right
Global Const $ICON_SEARROW2 = ChrW32(0x1F876)                               ; arrow pointing SE, down right
Global Const $ICON_SWARROW1 = ChrW(0x2199)                                  ; arrow pointing SW, down left
Global Const $ICON_SWARROW2 = ChrW32(0x1F877)                               ; arrow pointing SW, down left

Global Const $ICON_NARROW1 = ChrW(0x2191)                                   ; arrow pointing N, up
Global Const $ICON_NARROW2 = ChrW32(0x1F851)                                ; arrow pointing N, up
Global Const $ICON_WARROW1 = ChrW(0x2192)                                   ; arrow pointing W, left
Global Const $ICON_WARROW2 = ChrW32(0x1F850)                                ; arrow pointing W, left
Global Const $ICON_EARROW1 = ChrW(0x2194)                                   ; arrow pointing E, right
Global Const $ICON_EARROW2 = ChrW32(0x1F852)                                ; arrow pointing E, right
Global Const $ICON_SARROW1 = ChrW(0x2195)                                   ; arrow pointing S, down
Global Const $ICON_SARROW2 = ChrW32(0x1F853)                                ; arrow pointing S, down

Global Const $ICON_NTRI = Chr(0x23F6)                                       ; triangle pointing up
Global Const $ICON_STRI = Chr(0x23F7)                                       ; triangle pointing down
Global Const $ICON_WTRI = Chr(0x23F4)                                       ; triangle pointing left
Global Const $ICON_ETRI = Chr(0x23F5)                                       ; triangle pointing right
Global Const $ICON_UPTRI = Chr(0x23F6)                                      ; triangle pointing up
Global Const $ICON_DNTRI = Chr(0x23F7)                                      ; triangle pointing down
Global Const $ICON_LTRI = Chr(0x23F4)                                       ; triangle pointing left
Global Const $ICON_RTRI = Chr(0x23F5)                                       ; triangle pointing right

Global Const $ICON_BOX = Chr(0x23F9)                                        ; stop box
Global Const $ICON_DOT = Chr(0x23FA)                                        ; record circle/dot
Global Const $ICON_DVB = Chr(0x23F8)                                        ; double vertical pause bars


Global Const $ICON_PLAY = ChrW(0xE102)                                      ; play triangle
Global Const $ICON_PLAY1 = ChrW(0x23F5)                                     ; play triangle
Global Const $ICON_PLAY2 = ChrW(0x25B6)                                     ; play triangle
Global Const $ICON_PLAYR = ChrW(0x23F4)                                     ; reverse play triangle
Global Const $ICON_PLAYR2 = ChrW(0x25C0)                                    ; reverse play triangle
Global Const $ICON_PAUSE = ChrW(0xE103)                                     ; pause double vertical bar
Global Const $ICON_PAUSE2 = ChrW(0x23F8)                                    ; pause double vertical bar
Global Const $ICON_PLAYPAUSE = ChrW(0x23EF)                                 ; play/pause icon
Global Const $ICON_STOP = ChrW(0xE15B)                                      ; stop square
Global Const $ICON_STOP2 = ChrW(0x23F9)                                     ; stop square
Global Const $ICON_REC = ChrW(0x23FA)                                       ; record dot
Global Const $ICON_FASTFWD = ChrW(0x23E9)                                   ; fast forward
Global Const $ICON_REWIND = ChrW(0x23EA)                                    ; rewind
Global Const $ICON_VBAR = ChrW(0x2759) ; 0x23FD                             ; signle vertical bar
Global Const $ICON_NEXT = ChrW(0xE101)                                      ; next
Global Const $ICON_NEXT1 = $ICON_RTRI & $ICON_VBAR                          ; next step
Global Const $ICON_NEXT2 = ChrW(0x23ED)                                     ; next track/step
Global Const $ICON_PREV = ChrW(0xE100)                                      ; previous
Global Const $ICON_PREV1 = $ICON_VBAR & $ICON_LTRI                          ; previous step
Global Const $ICON_PREV2 = ChrW(0x23EE)                                     ; previous track/step
Global Const $ICON_EJECT = ChrW(0x23CF)                                     ; eject symbol

Global Const $ICON_STEPF = ChrW(0x21E5)                                     ; step forward
Global Const $ICON_STEPB = ChrW(0x21E4)                                     ; step backward
Global Const $ICON_STEPFB = ChrW(0x2B72)                                    ; step forward bold
Global Const $ICON_STEPBB = ChrW(0x2B70)                                    ; step backward bold
Global Const $ICON_STEPFOVER = ChrW(0x21B7)                                 ; step forward over
Global Const $ICON_STEPBOVER = ChrW(0x21B6)                                 ; step backward over
Global Const $ICON_STEPFOUT = ChrW(0x21AA)                                  ; step forward out/return
Global Const $ICON_STEPBOUT = ChrW(0x21A9)                                  ; step backward out
Global Const $ICON_STEPFINTO = ChrW(0x21A3)                                 ; step forward info
Global Const $ICON_STEPBINTO = ChrW(0x21A2)                                 ; step back into



Global Const $COLOR_NEUTRAL = 0xFDFDFD                                      ; neutral or default background color
Global Const $COLOR_GRAY2 = 0xFDFDFD                                        ; default button and gui background color
;Global Const $COLOR_RED = 0xFF0000
Global Const $COLOR_GREEN2 = 0x00FF00                                       ; total green
;Global Const $COLOR_BLUE = 0x0000FF
;Global Const $COLOR_YELLOW = 0xFFFF00
Global Const $COLOR_PURPLE2 = 0xFF00FF                                      ; total purple
;Global Const $COLOR_BLACK = 0x000000
;Global Const $COLOR_WHITE = 0xFFFFFF
;Global Const $COLOR_AZURE = 0x0080FF




; ===================================================================================================
; Function:    ChrW32
; Description: Converts a 32-bit Unicode Code Point into a valid UTF-16 Surrogate Pair string
; Parameter:   $iCodePoint - The 32-bit integer or hex value (e.g., 0x1F4BE)
; ===================================================================================================
Func ChrW32($iCodePoint)
	; Characters inside the Basic Multilingual Plane (0x0000 to 0xFFFF) fit inside a single ChrW
	If $iCodePoint <= 0xFFFF Then Return ChrW($iCodePoint)

	; 1. Shift the code point down into the surrogate working plane
	Local $iBase = $iCodePoint - 0x10000

	; 2. Apply bitwise shifts or standard division/modulo operators
	Local $iHighSurrogate = Int($iBase / 0x400) + 0xD800
	Local $iLowSurrogate = Mod($iBase, 0x400) + 0xDC00

	; 3. Concatenate the two 16-bit segments together into a single string stream
	Return ChrW($iHighSurrogate) & ChrW($iLowSurrogate)
EndFunc   ;==>ChrW32


