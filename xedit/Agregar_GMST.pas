{
  Agregar_GMST.pas  -  script para FNVEdit (xEdit)

  Añade a FalloutNV_NL.esp los textos del interfaz que el juego lleva dentro de FalloutNV.exe
  (Yes/No, Take, Talk to, menú principal, espera...). Lee gmst_exe_nl.txt de "Edit Scripts".
  No hace falta volver a crear el plugin entero.

  Uso: abre FNVEdit con FalloutNV.esm Y FalloutNV_NL.esp marcados.
       Clic derecho sobre FalloutNV_NL.esp -> Apply Script -> Agregar_GMST.
       Al cerrar FNVEdit, guarda FalloutNV_NL.esp.
}
unit AgregarGMST;

function Buscar(f: IInterface; edid: string): IInterface;
var
  g: IInterface;
begin
  Result := nil;
  g := GroupBySignature(f, 'GMST');
  if Assigned(g) then
    Result := MainRecordByEditorID(g, edid);
end;

procedure PonerTexto(rec: IInterface; valor: string);
var
  e: IInterface;
begin
  e := ElementBySignature(rec, 'DATA');
  if not Assigned(e) then
    e := Add(rec, 'DATA', True);
  if (GetEditValue(e) = '') and (ElementCount(e) > 0) then
    e := ElementByIndex(e, 0);
  SetEditValue(e, valor);
end;

function Initialize: integer;
var
  i, p, nNuevos, nCambiados, nYa: integer;
  lineas: TStringList;
  linea, edid, valor: string;
  esm, esp, rec, g: IInterface;
begin
  Result := 0;
  nNuevos := 0;
  nCambiados := 0;
  nYa := 0;
  esm := nil;
  esp := nil;
  for i := 0 to FileCount - 1 do begin
    if SameText(GetFileName(FileByIndex(i)), 'FalloutNV.esm') then esm := FileByIndex(i);
    if SameText(GetFileName(FileByIndex(i)), 'FalloutNV_NL.esp') then esp := FileByIndex(i);
  end;
  if not Assigned(esm) or not Assigned(esp) then begin
    AddMessage('ERROR: hay que cargar FalloutNV.esm y FalloutNV_NL.esp.');
    Result := 1;
    Exit;
  end;
  if not FileExists(ScriptsPath + 'gmst_exe_nl.txt') then begin
    AddMessage('ERROR: no encuentro gmst_exe_nl.txt en ' + ScriptsPath);
    Result := 1;
    Exit;
  end;

  lineas := TStringList.Create;
  lineas.LoadFromFile(ScriptsPath + 'gmst_exe_nl.txt');
  g := GroupBySignature(esp, 'GMST');
  if not Assigned(g) then
    g := Add(esp, 'GMST', True);

  for i := 0 to lineas.Count - 1 do begin
    linea := lineas[i];
    p := Pos(#9, linea);
    if p <= 1 then Continue;
    edid := Copy(linea, 1, p - 1);
    valor := Copy(linea, p + 1, Length(linea));
    valor := StringReplace(valor, '{{NL}}', #13#10, [rfReplaceAll]);
    valor := StringReplace(valor, '{{TAB}}', #9, [rfReplaceAll]);

    rec := Buscar(esp, edid);
    if Assigned(rec) then begin
      nYa := nYa + 1;           // ya traducido por Traduccion_NL (estaba en el .esm)
      Continue;
    end;
    rec := Buscar(esm, edid);
    if Assigned(rec) then begin
      rec := wbCopyElementToFile(rec, esp, False, True);
      PonerTexto(rec, valor);
      nCambiados := nCambiados + 1;
    end else begin
      rec := Add(g, 'GMST', True);
      SetElementEditValues(rec, 'EDID', edid);
      PonerTexto(rec, valor);
      nNuevos := nNuevos + 1;
    end;
  end;
  lineas.Free;

  AddMessage('');
  AddMessage('LISTO: ' + IntToStr(nNuevos) + ' textos del interfaz añadidos, '
    + IntToStr(nCambiados) + ' sustituidos, ' + IntToStr(nYa) + ' ya estaban.');
  AddMessage('Cierra FNVEdit y guarda FalloutNV_NL.esp (dejalo marcado y pulsa OK).');
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

end.
