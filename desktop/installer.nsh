!macro customInit
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\AI行情助手"
!macroend

!macro customUnInstall
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "是否同时删除用户数据、自选、模拟交易和设置？默认选择“否”将保留数据。" /SD IDNO IDNO keepData
  RMDir /r "$APPDATA\AI行情助手"
  keepData:
!macroend
