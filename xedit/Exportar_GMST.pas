{
  Exportar_GMST.pas  -  script para FNVEdit (xEdit)

  Exporta los Game Settings de texto de FalloutNV.esm (textos del interfaz: "Take",
  "Talk to", "How long would you like to wait?", Yes/No, menús...) a gmst_en.txt,
  en la carpeta "Edit Scripts". xTranslator no exporta estos textos.

  Uso: en FNVEdit, clic derecho sobre FalloutNV.esm -> Apply Script -> Exportar_GMST.
  Después: python traducir_fnv.py gmst "<carpeta Edit Scripts>\gmst_en.txt"
}
unit ExportarGMST;

function Escapar(s: string): string;
begin
  Result := StringReplace(s, #13#10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #13, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #9, '{{TAB}}', [rfReplaceAll]);
end;

function ValorTexto(rec: IInterface): string;
var
  e: IInterface;
begin
  Result := '';
  e := ElementBySignature(rec, 'DATA');
  if not Assigned(e) then Exit;
  Result := GetEditValue(e);
  if (Result = '') and (ElementCount(e) > 0) then
    Result := GetEditValue(ElementByIndex(e, 0));
end;

function Initialize: integer;
var
  i, j, n: integer;
  f, g, rec: IInterface;
  edid, valor, nombre: string;
  lista, vistos: TStringList;
begin
  Result := 0;
  lista := TStringList.Create;
  vistos := TStringList.Create;
  vistos.Sorted := True;
  vistos.CaseSensitive := False;

  // Revisa todos los archivos cargados, incluido el módulo "FalloutNV.exe" que FNVEdit
  // usa para los registros integrados en el juego. No incluye FalloutNV_NL.esp.
  for j := 0 to FileCount - 1 do begin
    f := FileByIndex(j);
    nombre := GetFileName(f);
    if SameText(nombre, 'FalloutNV_NL.esp') then Continue;
    g := GroupBySignature(f, 'GMST');
    if not Assigned(g) then Continue;
    n := 0;
    for i := 0 to ElementCount(g) - 1 do begin
      rec := ElementByIndex(g, i);
      edid := GetElementEditValues(rec, 'EDID');
      // Los Game Settings de texto empiezan por "s" minúscula (sTake, sYes...)
      if (Copy(edid, 1, 1) = 's') and (vistos.IndexOf(edid) < 0) then begin
        valor := ValorTexto(rec);
        if valor <> '' then begin
          lista.Add(edid + #9 + Escapar(valor));
          vistos.Add(edid);
          n := n + 1;
        end;
      end;
    end;
    AddMessage(nombre + ': ' + IntToStr(n) + ' Game Settings de texto.');
  end;
  vistos.Free;
  lista.SaveToFile(ScriptsPath + 'gmst_en.txt');
  AddMessage('');
  AddMessage('LISTO: ' + IntToStr(lista.Count) + ' Game Settings de texto exportados a:');
  AddMessage('  ' + ScriptsPath + 'gmst_en.txt');
  AddMessage('Puedes cerrar FNVEdit sin guardar nada.');
  lista.Free;
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

end.
