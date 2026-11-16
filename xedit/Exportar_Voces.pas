{
  Exportar_Voces.pas  -  script para FNVEdit (xEdit)

  Exporta lo necesario para generar las voces en holandés:
    - voces_nl.txt     una línea por respuesta de diálogo (INFO) de FalloutNV_NL.esp:
                       FormID, número de respuesta, emoción, intensidad, misión,
                       notas para el actor, texto en holandés y texto original en inglés.
    - voces_tipos.txt  los tipos de voz (VTYP) de FalloutNV.esm y si son femeninos.

  Uso: abre FNVEdit con FalloutNV.esm Y FalloutNV_NL.esp marcados.
       Clic derecho sobre FalloutNV_NL.esp -> Apply Script -> Exportar_Voces.
       No modifica nada: al cerrar FNVEdit no hace falta guardar.
  Después: python voces_fnv.py contar "<...>\Fallout - Voices1.bsa" "<...>\Edit Scripts\voces_nl.txt"
}
unit ExportarVoces;

function Escapar(s: string): string;
begin
  Result := StringReplace(s, #13#10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #13, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #9, '{{TAB}}', [rfReplaceAll]);
end;

// Hijo directo cuyo nombre contiene "texto" (sin distinguir mayúsculas).
function Hijo(e: IInterface; texto: string): IInterface;
var
  i: integer;
begin
  Result := nil;
  if not Assigned(e) then Exit;
  for i := 0 to ElementCount(e) - 1 do
    if Pos(LowerCase(texto), LowerCase(Name(ElementByIndex(e, i)))) > 0 then begin
      Result := ElementByIndex(e, i);
      Exit;
    end;
end;

function Valor(e: IInterface): string;
begin
  Result := '';
  if Assigned(e) then Result := GetEditValue(e);
end;

// Primera palabra (el Editor ID) de un valor como 'VCG01 "Ain't That..." [QUST:00104C1C]'
function PrimeraPalabra(s: string): string;
var
  p: integer;
begin
  p := Pos(' ', s);
  if p > 0 then Result := Copy(s, 1, p - 1) else Result := s;
end;

function Initialize: integer;
var
  i, j, nInfo, nResp: integer;
  esm, esp, rec, maestro, resps, respsEn, resp, respEn, trdt, g: IInterface;
  lista, tipos: TStringList;
  formid, numero, emocion, intensidad, mision, notas, nl, en: string;
  flags: integer;
begin
  Result := 0;
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

  lista := TStringList.Create;
  tipos := TStringList.Create;
  nInfo := 0;
  nResp := 0;

  AddMessage('Exportando respuestas de diálogo...');
  for i := 0 to RecordCount(esp) - 1 do begin
    rec := RecordByIndex(esp, i);
    if Signature(rec) <> 'INFO' then Continue;
    resps := ElementByName(rec, 'Responses');
    if not Assigned(resps) then Continue;
    maestro := MasterOrSelf(rec);
    respsEn := ElementByName(maestro, 'Responses');
    formid := IntToHex(GetLoadOrderFormID(rec), 8);
    mision := PrimeraPalabra(GetElementEditValues(rec, 'QSTI'));
    nInfo := nInfo + 1;
    for j := 0 to ElementCount(resps) - 1 do begin
      resp := ElementByIndex(resps, j);
      trdt := ElementBySignature(resp, 'TRDT');
      numero := Valor(Hijo(trdt, 'Response number'));
      if numero = '' then numero := IntToStr(j + 1);
      emocion := Valor(Hijo(trdt, 'Emotion Type'));
      intensidad := Valor(Hijo(trdt, 'Emotion Value'));
      notas := Valor(ElementBySignature(resp, 'NAM2'));
      nl := Valor(ElementBySignature(resp, 'NAM1'));
      en := '';
      if Assigned(respsEn) and (j < ElementCount(respsEn)) then begin
        respEn := ElementByIndex(respsEn, j);
        en := Valor(ElementBySignature(respEn, 'NAM1'));
      end;
      if nl = '' then Continue;
      lista.Add(formid + #9 + numero + #9 + emocion + #9 + intensidad + #9 + mision + #9
        + Escapar(notas) + #9 + Escapar(nl) + #9 + Escapar(en));
      nResp := nResp + 1;
    end;
  end;
  lista.SaveToFile(ScriptsPath + 'voces_nl.txt');

  AddMessage('Exportando tipos de voz...');
  g := GroupBySignature(esm, 'VTYP');
  if Assigned(g) then
    for i := 0 to ElementCount(g) - 1 do begin
      rec := ElementByIndex(g, i);
      flags := GetElementNativeValues(rec, 'DNAM');
      if (flags and 2) <> 0 then
        tipos.Add(GetElementEditValues(rec, 'EDID') + #9 + 'F')
      else
        tipos.Add(GetElementEditValues(rec, 'EDID') + #9 + 'M');
    end;
  tipos.SaveToFile(ScriptsPath + 'voces_tipos.txt');

  AddMessage('');
  AddMessage('LISTO: ' + IntToStr(nResp) + ' respuestas de ' + IntToStr(nInfo) + ' registros INFO -> voces_nl.txt');
  AddMessage(IntToStr(tipos.Count) + ' tipos de voz -> voces_tipos.txt');
  AddMessage('Carpeta: ' + ScriptsPath);
  AddMessage('Puedes cerrar FNVEdit sin guardar nada.');
  lista.Free;
  tipos.Free;
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

end.
