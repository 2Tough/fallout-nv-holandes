{
  Comprobar_Orden_INFO.pas  -  script para FNVEdit (xEdit)

  SOLO COMPRUEBA (no cambia nada). Compara, en cada tema de diálogo de FalloutNV_NL.esp,
  el orden original de las frases (INOM de FalloutNV.esm) con el orden que resulta con la
  traducción (INOA de FalloutNV_NL.esp), y guarda un informe en Edit Scripts:
      orden_info_informe.txt
  Por cada tema distinto: Editor ID, FormID, número de frases, cuántas están en el .esp,
  si es una misión (Quest) o genérico, y las dos listas de FormIDs.

  Uso: FNVEdit con FalloutNV.esm + FalloutNV_NL.esp -> clic derecho en FalloutNV_NL.esp ->
       Apply Script -> Comprobar_Orden_INFO. No hace falta guardar.
}
unit ComprobarOrdenINFO;

var
  esp: IInterface;

function Lista(dial: IInterface; sig: string): IInterface;
var
  i: integer;
  e: IInterface;
begin
  Result := ElementBySignature(dial, sig);
  if Assigned(Result) then Exit;
  for i := 0 to ElementCount(dial) - 1 do begin
    e := ElementByIndex(dial, i);
    if Copy(Name(e), 1, 4) = sig then begin
      Result := e;
      Exit;
    end;
  end;
end;

function Ids(l: IInterface): string;
var
  k: integer;
  r: IInterface;
begin
  Result := '';
  for k := 0 to ElementCount(l) - 1 do begin
    r := LinksTo(ElementByIndex(l, k));
    if Assigned(r) then
      Result := Result + IntToHex(GetLoadOrderFormID(r), 8) + ' '
    else
      Result := Result + '? ';
  end;
end;

function EnEsp(rec: IInterface): boolean;
var
  k: integer;
begin
  Result := False;
  rec := MasterOrSelf(rec);
  for k := 0 to OverrideCount(rec) - 1 do
    if Equals(GetFile(OverrideByIndex(rec, k)), esp) then begin
      Result := True;
      Exit;
    end;
end;

function Initialize: integer;
var
  i, k, nBien, nMal, nSinDatos, nEsp, nMision: integer;
  dial, maestro, deseado, actual, info: IInterface;
  informe: TStringList;
  tipo, idsD, idsA, mision: string;
begin
  Result := 0;
  esp := nil;
  for i := 0 to FileCount - 1 do
    if SameText(GetFileName(FileByIndex(i)), 'FalloutNV_NL.esp') then esp := FileByIndex(i);
  if not Assigned(esp) then begin
    AddMessage('ERROR: hay que cargar FalloutNV.esm y FalloutNV_NL.esp.');
    Result := 1;
    Exit;
  end;

  informe := TStringList.Create;
  nBien := 0; nMal := 0; nSinDatos := 0; nMision := 0;
  AddMessage('Comprobando (sin cambiar nada)...');

  for i := 0 to RecordCount(esp) - 1 do begin
    dial := RecordByIndex(esp, i);
    if Signature(dial) <> 'DIAL' then Continue;
    maestro := MasterOrSelf(dial);
    if Equals(maestro, dial) then Continue;
    deseado := Lista(maestro, 'INOM');
    actual := Lista(dial, 'INOA');
    if not Assigned(actual) then actual := Lista(dial, 'INOM');
    if not Assigned(deseado) or not Assigned(actual) then begin
      nSinDatos := nSinDatos + 1;
      Continue;
    end;
    idsD := Ids(deseado);
    idsA := Ids(actual);
    if idsD = idsA then begin
      nBien := nBien + 1;
      Continue;
    end;
    nMal := nMal + 1;
    nEsp := 0;
    for k := 0 to ElementCount(deseado) - 1 do begin
      info := LinksTo(ElementByIndex(deseado, k));
      if Assigned(info) and EnEsp(info) then nEsp := nEsp + 1;
    end;
    tipo := GetElementEditValues(maestro, 'DATA\Type');
    mision := GetElementEditValues(maestro, 'Added Quests\Added Quest\QSTI');
    if Pos('VMS', mision) + Pos('VCG', mision) + Pos('VMQ', mision) + Pos('VFS', mision) > 0 then
      nMision := nMision + 1;
    informe.Add('TEMA' + #9 + EditorID(dial) + #9 + IntToHex(GetLoadOrderFormID(dial), 8) + #9
      + tipo + #9 + mision + #9 + IntToStr(ElementCount(deseado)) + ' frases' + #9
      + IntToStr(nEsp) + ' en el esp');
    informe.Add('ESPERADO' + #9 + idsD);
    informe.Add('REAL' + #9 + idsA);
  end;

  informe.SaveToFile(ScriptsPath + 'orden_info_informe.txt');
  AddMessage('');
  AddMessage('Con el orden correcto: ' + IntToStr(nBien));
  AddMessage('Con el orden distinto: ' + IntToStr(nMal));
  AddMessage('Sin lista de orden:    ' + IntToStr(nSinDatos));
  AddMessage('Informe: ' + ScriptsPath + 'orden_info_informe.txt');
  AddMessage('No ha cambiado nada: puedes cerrar sin guardar.');
  informe.Free;
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

end.
