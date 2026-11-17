#include-once

#cs

	change this to work in the main queue only
	$g_oDevMain

	change the selection box to pick from $g_oViSelect

	add pause, forward and backwards buttons




	;add debug edit box to enter script/visa commands and a combo select box to select which item to send it to
	;	another edit box to show the results, an execute button, save and load buttons for the edit field

	edit box for output showing outgoing visa command and incomming data

	save button to save last output received to a file
	open and save and execute buttons
	combo box to select the visa device

	edit box for input of visa command script

#ce



#include <Math.au3>
#include <GUIConstants.au3>
#include <GUIConstantsEx.au3>
#include <AutoItConstants.au3>
#include <MsgBoxConstants.au3>
#include <StaticConstants.au3>
#include <GuiEdit.au3>

#include "myconstants.au3"
#include "filemisc.au3"
#include "visascpi.au3"
#include "winfuncs.au3"
#include "winmgmt.au3"
#include "deque.au3"





Global $g_dg_iReadTimer, $g_dg_iRefreshInterval = 950
Global $g_db_iStepInterval = 500


; GUI elements
Global $g_dg_cIpAddr, $g_dg_cDevID, $g_dg_cInput, $g_dg_cOutput, $g_dg_iTabIdx, $g_dg_oDev
Global $g_dg_outFile, $g_dg_inFile, $g_dg_lastOut, $g_dg_cStack, $g_dg_cQueue, $g_dg_cPlay




;---------------------------------------------------------------------------
;---------------------------------------------------------------------------
;---------------------------------------------------------------------------
;---------------------------------------------------------------------------
; initialization functions


; called after gui window is shown during init/setup
Func dgTab_init()
	;LoopRegister("debugTab_Loop")
	$g_dg_oDev = dgTab_GetIP()
	dgTab_IpRefresh()
	$g_dg_iReadTimer = TimerInit()
EndFunc   ;==>dgTab_init





; called during the Tab control section of main gui window setup
Func dgTab_GuiCreate($iTabIdx, $oCanvas, $hCanvas)
	$g_dg_iTabIdx = $iTabIdx                   ; save for later to determine if we are the selected tab

	Local $iW = $oCanvas.Item('iW')
	Local $iH = $oCanvas.Item('iH')
	Local $iX = 5
	Local $iY = 3
	Local $w1, $x2
	Local $iW2 = 250                            ; width of column 2
	Local $iWM = $iW - $iX - $iX - $iW2         ; width/height inside margins
	Local $iHM = $iH - $iY - $iY
	Local $iHbar = 30                           ; height of the middle bar
	Local $iH1 = Int(($iHM - $iHbar) * 0.66)    ; height of the upper edit fields
	Local $iH2 = ($iHM - $iHbar) - $iH1         ; height of the lower edit fields
	Local $iYbar = $iY + $iH1 + 5               ; top of middle bar



	$g_dg_cOutput = GUICtrlCreateInput("", $iX, $iY, $iWM, $iH1, BitOR($GUI_SS_DEFAULT_INPUT, $ES_AUTOVSCROLL, $ES_MULTILINE, $WS_VSCROLL, $ES_WANTRETURN))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKTOP, $GUI_DOCKLEFT, $GUI_DOCKRIGHT, $GUI_DOCKBOTTOM))
	$g_dg_cStack = GUICtrlCreateInput("", $iX + $iWM, $iY, $iW2, $iH1, BitOR($GUI_SS_DEFAULT_INPUT, $ES_AUTOVSCROLL, $ES_MULTILINE, $WS_VSCROLL, $ES_WANTRETURN))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKTOP, $GUI_DOCKBOTTOM, $GUI_DOCKWIDTH))


	$iX2 = $iX
	GUICtrlCreateButton($ICON_SAVE, $iX2, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 12, 600, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_SaveOutput")
	GUICtrlSetTip(-1, "Save the last VISA/SCPI response to a file")
	$iX2 += 25 + 5

	$w1 = Int(($iWM - 310) / 2)
	GUICtrlCreateLabel("Device:", $iX2, $iYbar + 3, 40, 17, BitOR($GUI_SS_DEFAULT_LABEL, $SS_RIGHT))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	$g_dg_cIpAddr = GUICtrlCreateCombo("", $iX2 + 40, $iYbar, $w1, 22)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetOnEvent(-1, "dgTab_IpRefresh")
	GUICtrlCreateButton($ICON_SEARCH, $iX2 + 40 + $w1, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 12, 600, 0, "Segoe UI Symbol")
	GUICtrlSetTip(-1, "Scan subnet 192.168.0.0 for possible VISA devices")
	GUICtrlSetOnEvent(-1, "dgTab_ScanNetwork")
	$iX2 += 40 + $w1 + 25 + 5

	GUICtrlCreateLabel("DevID:", $iX2, $iYbar + 3, 40, 17, BitOR($GUI_SS_DEFAULT_LABEL, $SS_RIGHT))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	$g_dg_cDevID = GUICtrlCreateInput("", $iX2 + 40, $iYbar, $w1, 20, BitOR($GUI_SS_DEFAULT_INPUT, $ES_READONLY))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKHEIGHT, $GUI_DOCKRIGHT))
	GUICtrlCreateButton($ICON_REFRESH, $iX2 + 40 + $w1, $iYbar - 3, 25, 25)
	GUICtrlSetFont(-1, 8, 600, 0, "Segoe UI Symbol")
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetTip(-1, "Reconnect")
	GUICtrlSetOnEvent(-1, "dgTab_IpRefresh")
	$iX2 += 65 + $w1 + 5

	GUICtrlCreateButton($ICON_OPEN, $iX2, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 11, -1, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_OpenInput")
	GUICtrlSetTip(-1, "Open a VISA/SCPI script file")
	$iX2 += 25 + 5
	GUICtrlCreateButton($ICON_SAVE, $iX2, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 12, 600, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_SaveInput")
	GUICtrlSetTip(-1, "Save this VISA/SCPI script to a file")
	$iX2 += 25 + 5

	GUICtrlCreateButton($ICON_INFO, $iX2, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 10, -1, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_ShowInfo")
	GUICtrlSetTip(-1, "Dump oDev to output window")
	$iX2 += 25 + 5

	;Local $cSend = GUICtrlCreateButton("Send", $iX2, $iYbar - 3, 50, 25)
	;GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	;GUICtrlSetOnEvent(-1, "dgTab_PlayBtn")
	;GUICtrlSetTip(-1, "Send the VISA/SCPI commands to the device")
	;$iX2 += 50

	Global $g_dg_cPlay = GUICtrlCreateButton($ICON_PLAY, $iX2, $iYbar - 3, 25, 25, $BS_DEFPUSHBUTTON)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 12, 400, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_PlayBtn")
	GUICtrlSetTip(-1, "Push the script statements into the queue")
	$iX2 += 25
	GUICtrlCreateButton($ICON_NEXT, $iX2, $iYbar - 3, 25, 25)
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))
	GUICtrlSetFont(-1, 12, 400, 0, "Segoe UI Symbol")
	GUICtrlSetOnEvent(-1, "dgTab_StepBtn")
	GUICtrlSetTip(-1, "Process next script statement")
	$iX2 += 25



	$g_dg_cInput = GUICtrlCreateInput("", $iX, $iY + $iH1 + $iHbar, $iWM, $iH2, BitOR($GUI_SS_DEFAULT_INPUT, $ES_MULTILINE, $WS_VSCROLL, $ES_WANTRETURN))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKLEFT, $GUI_DOCKBOTTOM, $GUI_DOCKRIGHT, $GUI_DOCKHEIGHT))
	$g_dg_cQueue = GUICtrlCreateInput("", $iX + $iWM, $iY + $iH1 + $iHbar, $iW2, $iH2, BitOR($GUI_SS_DEFAULT_INPUT, $ES_MULTILINE, $WS_VSCROLL, $ES_WANTRETURN))
	GUICtrlSetResizing(-1, BitOR($GUI_DOCKRIGHT, $GUI_DOCKBOTTOM, $GUI_DOCKSIZE))

	__AccelKeyAdd("^{Enter}", $g_dg_cPlay)

EndFunc   ;==>dgTab_GuiCreate





; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------


; ---------------------------------------------------------------------------
; GUI Event Handler Functions


Func dgTab_ScanNetwork()
	__viScanSubnet()
EndFunc   ;==>dgTab_ScanNetwork

Func dgTab_SaveOutput()
	Local $sDrive, $sDir, $sName, $sExt
	_PathSplit($g_dg_outFile, $sDrive, $sDir, $sName, $sExt)
	Local $sFile = FileSaveDialog("Save Output", $sDrive & $sDir, "(*.*)", BitOR($FD_PATHMUSTEXIST, $FD_PATHMUSTEXIST), $sName, $g_hMainGui)
	If $sFile = "" Then Return
	$g_dg_outFile = $sFile
	Local $hFile = FileOpen($sFile, 18) ; 1=file 2=(over)write, 16=binary
	If $hFile <= 0 Then Return
	FileWrite($hFile, $g_dg_lastOut)
	FileClose($hFile)
EndFunc   ;==>dgTab_SaveOutput

Func dgTab_SaveInput()
	Local $sDrive, $sDir, $sName, $sExt
	_PathSplit($g_dg_inFile, $sDrive, $sDir, $sName, $sExt)
	Local $sFile = FileSaveDialog("Save Script", $sDrive & $sDir, "(*.txt)", BitOR($FD_PATHMUSTEXIST, $FD_PATHMUSTEXIST), $sName, $g_hMainGui)
	If $sFile = "" Then Return
	$g_dg_inFile = $sFile
	Local $hFile = FileOpen($sFile, 2) ; open for 2=(over) writing
	If $hFile <= 0 Then Return
	FileWrite($hFile, GUICtrlRead($g_dg_cInput))
	FileClose($hFile)
EndFunc   ;==>dgTab_SaveInput

Func dgTab_OpenInput()
	Local $sDrive, $sDir, $sName, $sExt
	_PathSplit($g_dg_inFile, $sDrive, $sDir, $sName, $sExt)
	Local $sFile = FileOpenDialog("Open Script", $sDrive & $sDir, "(*.txt)", BitOR($FD_PATHMUSTEXIST, $FD_FILEMUSTEXIST), $sName, $g_hMainGui)
	If $sFile = "" Then Return
	$g_dg_inFile = $sFile
	Local $hFile = FileOpen($sFile, 0) ; read mode
	If $hFile <= 0 Then Return
	GUICtrlSetData($g_dg_cInput, FileRead($hFile))
	FileClose($hFile)
EndFunc   ;==>dgTab_OpenInput

Func dgTab_PlayBtn()
	If Not __viResolveInstrument($g_dg_oDev) Then Return
	Local $bPlay = Not $g_dg_oDev.Item('dgPlay')        ; toggle play mode
	If $bPlay And __viIsIdle($g_dg_oDev) Then ; __DequeIsEmpty($g_dg_oDev.Item('qreq')) Then
		dgTab_EnQueue()
		;$bPlay = True
	EndIf
	$g_dg_oDev.Item('dgPlay') = $bPlay
	GUICtrlSetData($g_dg_cPlay, $bPlay ? $ICON_PAUSE : $ICON_PLAY)
	$g_dg_oDev.Item('dgStep') = False                   ; set step to false so we do not accidentally execute next step if in pause mode
EndFunc   ;==>dgTab_PlayBtn

Func dgTab_StepBtn()
	If Not __viResolveInstrument($g_dg_oDev) Then Return
	Local $bPlay = Not Not $g_dg_oDev.Item('dgPlay')    ; ensure we are in pause mode
	If $bPlay Then
		$g_dg_oDev.Item('dgPlay') = False
		GUICtrlSetData($g_dg_cPlay, $ICON_PLAY)
	EndIf
	Local $bIsEmpty = __viIsIdle($g_dg_oDev) ; __DequeIsEmpty($g_dg_oDev.Item('qreq'))
	If $bIsEmpty Then dgTab_EnQueue()
	$g_dg_oDev.Item('dgStep') = Not $bIsEmpty           ; set step flag to true so we execute the next step

	; if in play mode then set to pause mode
	; flag to execute current statement and move to next
	;
	; need a method of controlling execution flow thru flag variables
	; flags:
	; 	diagPlay = true if in play mode else we are in pause mode
	; 	diagStep = true to execute current command and pause at the next step
	;   diagTimer = timer for a short pause between executing each step
	;   diagStepInterval = interval between steps when executing normally
	; op:
	;	if pause is true and step is false then hold/pause and not execute the next step
	; 	after executing current step clear the step flag
	; 	if exists 'dg' then add a 500ms pause between each statement - use a diagtimer variable to do async sleep
	;
EndFunc   ;==>dgTab_StepBtn

Func dgTab_EnQueue()
	If Not __viResolveInstrument($g_dg_oDev) Then Return
	$g_dg_oDev.Item('dg') = ""
	Local $i
	Local $sReq = GUICtrlRead($g_dg_cInput)
	Local $aReq = StringSplit($sReq, @LF)
	Local $n = $aReq[0]
	If $n <= 0 Then Return
	For $i = 1 To $n
		$sReq = StringStripWS($aReq[$i], 3)
		__viCmd($g_dg_oDev, $sReq)
	Next
	$g_dg_oDev.Item('dgStepInterval') = $g_db_iStepInterval
	$g_dg_oDev.Item('dgTimer') = TimerInit()
EndFunc   ;==>dgTab_EnQueue


Func dgTab_ShowInfo()
	__GUICtrlEdit_Append($g_dg_cOutput, __sPrintVar($g_dg_oDev, @CRLF & "    ", "oDev") & @CRLF)
EndFunc   ;==>dgTab_ShowInfo

Func dgTab_IpRefresh()
	Local $oDevOld = $g_dg_oDev
	dgTab_GetID()
	If $g_dg_oDev <> $oDevOld Then
		If __IsDictionary($oDevOld) Then
			If $oDevOld.Exists('dg') Then
				$oDevOld.Remove('dg')                   ; remove debug flag from old selection
				$oDevOld.Item('dgPlay') = True
				$oDevOld.Item('dgStep') = False
				$oDevOld.Item('dgStepInterval') = $g_db_iStepInterval
				$oDevOld.Item('dgTimer') = TimerInit()
			EndIf
		EndIf
		GUICtrlSetData($g_dg_cOutput, "")
		GUICtrlSetData($g_dg_cQueue, "")
		GUICtrlSetData($g_dg_cStack, "")
	EndIf
	If __IsDictionary($g_dg_oDev) Then
		$g_dg_oDev.Item('dg') = ''                      ; add debug flag to new selection
		$g_dg_oDev.Item('dgPlay') = True
		$g_dg_oDev.Item('dgStep') = False
		$g_dg_oDev.Item('dgStepInterval') = $g_db_iStepInterval
		$g_dg_oDev.Item('dgTimer') = TimerInit()
		dgTab_ShowInfo()
	EndIf
EndFunc   ;==>dgTab_IpRefresh

Func dgTab_GetIP()
	Return __viGUIGetIP($g_dg_cIpAddr)
EndFunc   ;==>dgTab_GetIP

Func dgTab_GetID()
	__viGUIGetID($g_dg_cDevID, $g_dg_cIpAddr, $g_dg_oDev, "", "")
EndFunc   ;==>dgTab_GetID





; ----------------------
; ----------------------
; ----------------------
; ----------------------
; ----------------------

; config file functions

Global $dgTab_ConfigSection = "Diag"
Global $g_configFile

Func dgTab_ConfigWrite()
	__viSaveIP($g_dg_cIpAddr, $dgTab_ConfigSection)
EndFunc   ;==>dgTab_ConfigWrite

Func dgTab_ConfigRead()
	If $g_configFile = "" Then Return
	If Not FileExists($g_configFile) Then Return
	__viLoadIP($g_dg_cIpAddr, $dgTab_ConfigSection)
EndFunc   ;==>dgTab_ConfigRead




; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------
; ----------------------------

; ---------------------------------------------------------------------------
; Background Polling Subroutines

Func dgTab_Loop()
	If TimerDiff($g_dg_iReadTimer) < $g_dg_iRefreshInterval Then Return
	$g_dg_iReadTimer = TimerInit()

	If GUICtrlRead($g_cTab) <> $g_dg_iTabIdx Then Return
	If Not __IsDictionary($g_dg_oDev) Then Return
	;Local $s = ""
	;If $g_dg_oDev.Exists('dg') Then $s = $g_dg_oDev.Item('dg')
	;If $s = "" Then Return

	;_GUICtrlEdit_AppendText($g_dg_cOutput, $s)

	;$g_dg_oDev.Item('dg') = ''
EndFunc   ;==>dgTab_Loop


;; Flicker-Free Append & Scroll Function
;Func _GUICtrlEdit_Append($hEdit, $sText)
;    GUICtrlSendMsg($hEdit, $EM_SETSEL, -1, -1)  			; 1. Move the caret/cursor to the very end of the text ($EM_SETSEL)
;    GUICtrlSendMsg($hEdit, $EM_REPLACESEL, True, $sText)    ; 2. Replace the empty selection at the end with your new text ($EM_REPLACESEL)    ; The 'True' parameter enables the Undo buffer (False bypasses it)
;    GUICtrlSendMsg($idEdit, $EM_SCROLLCARET, 0, 0)          ; 3. Force the control to scroll down to the new caret position ($EM_SCROLLCARET)
;EndFunc
