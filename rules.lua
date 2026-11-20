local mode = arg[1]
if mode == "award" then
  local correct, combo = tonumber(arg[2]), tonumber(arg[3])
  local xp = 0
  if correct == 1 then xp = 10 + math.min(combo, 5) * 2 end
  print(xp)
elseif mode == "level" then
  local total = tonumber(arg[2])
  local levels = {{0,"Rookie"},{50,"Learner"},{150,"Scholar"},{300,"Expert"},{600,"Master"}}
  local name, nxt = levels[1][2], 0
  for i, l in ipairs(levels) do
    if total >= l[1] then
      name = l[2]
      nxt = levels[i+1] and levels[i+1][1] or l[1]
    end
  end
  print(name); print(nxt)
elseif mode == "schedule" then
  local box, correct = tonumber(arg[2]), tonumber(arg[3])
  local days = {0, 1, 2, 4, 7, 14}
  if correct == 1 then box = math.min(box + 1, 5) else box = 1 end
  print(box); print(days[box + 1])
end
