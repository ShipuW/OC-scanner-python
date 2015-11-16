# -*- coding: utf-8 -*-

import sys, os, glob
import json, re
import subprocess
import urllib2


def initialize():
  # 初始化全局变量
  global SYSTEM
  SYSTEM = ""

  pass

def download():
  # 由服务器下载json
  url = "http://localhost/test.json"
  ext = url[url.rindex("."):]
  filename = url[url.rindex("/")+1:url.rindex(".")]
  folder = os.getcwd()
  #print folder
  try:
    f = urllib2.urlopen(url)
    with open(filename+ext,"wb") as code:
        code.write(f.read())
  except:
      print("\tparameter error!the url is error?")
      sys.exit(0)
  print("\tdownload OK,you can find it in %s" %folder)
  
  return True
  
  
  
  
def check_with_config(config_file):
  '''
  按照配置文件检查打点
  '''
  objc_source_exts = ['*.m', '*.mm']

  with open(config_file) as f:
    cfg = json.load(f)

  if not check_config(cfg):
    exit(1)

  options = cfg['options']
  search_paths = options['search_paths']

  track_groups = cfg['groups']
  expected_tracks = load_track_defs(track_groups)

  source_files = list_files(search_paths, objc_source_exts)
  existing_tracks = list_tracks(source_files)
  ret = compare_tracks(expected_tracks, existing_tracks)
  if not ret:
    exit(1)


def check_config(cfg):
  '''
  检查配置项
  '''
  if not cfg.get('options'):
    print '[Error] missing "options" section'
    return False
  if not cfg['options'].get('search_paths'):
    print '[Error] missing "search_paths" section'
    return False
  groups = cfg.get('groups')
  if not groups:
    print '[Error] missing "groups" section'
    return False
  return True


def list_files(search_paths, exts):
  global SYSTEM
  '''
  递归列出目录下所有符合扩展名的文件
  '''
  all_files = []

  for path in search_paths:
    path = os.path.abspath(path)
    for ext in exts:
      files = [y for x in os.walk(path) for y in glob.glob(os.path.join(x[0], ext))]
      if files != []:
        if ext == "*.m" or ext =="*.mm":
          SYSTEM = "ios"
        else:
          SYSTEM = "android"                 #确认系统
      else: 
        SYSTEM = "未找到扫描文件"
      print SYSTEM
      all_files.extend(files)
      
  return all_files


def load_track_defs(groups):
  '''
  解析配置文件里的打点列表
  '''
  all_tracks = []

  for group in groups:
    # 页面打点转为enter和leave两条
    page_def = group.get('page')
    if page_def:
      if not page_def.get('track'):
        # 不需要打点，比如只是个分组，不是页面
        pass
      elif page_def.get('ignored'):
        page_name = page_def.get('name') or ''
        printUnicode(u'[Warning] 忽略的页面打点，请人工检查 - 页面: %s' % (page_name,))
      else:
        track = dict(page_def)
        track['type'] = 'pageAppear'
        all_tracks.append(track)

        track = dict(page_def)
        track['type'] = 'pageDisAppear'
        all_tracks.append(track)

    # 控件打点，控件一般都关联在一个页面
    controls_def = group.get('controls')
    for ctrl_def in controls_def:
      if ctrl_def.get('ignored'):
        page_name = page_def['name'] if page_def else ''
        printUnicode(u'[Warning] 忽略的打点，请人工检查 - 页面: %s, 说明: %s' \
                     % (page_name, ctrl_def['name']))
        continue

      track = dict(ctrl_def)
      track['type'] = 'ctrlClicked'
      if page_def:
        track['page'] = page_def
      all_tracks.append(track)
    
    
    #自定义打点
    custom_def = group.get('customs')
    if custom_def:
    
      for ctm_def in custom_def:
        if ctm_def.get('ignored'):
          page_name = page_def['name'] if page_def else ''
          printUnicode(u'[Warning] 忽略的自定义打点，请人工检查 - 页面: %s, 说明: %s' \
          % (page_name, ctm_def['name']))
          continue
        track = dict(ctm_def)
        track['type'] = 'commitEvent'
        if page_def:
          track['page'] = page_def
        all_tracks.append(track)



  return all_tracks


def list_tracks(files):
  '''
  列出源代码文件内所有的打点信息
  '''
  all_tracks = []
  #print files
  for filename in files:
    # 列出打点，再匹配到所属的类名方法名
    tracks = find_tracks_in_source(filename)
    if not tracks:
      continue     
      pass
    methods = parse_methods_in_source(filename)
    for track in tracks:
      for m in methods:
        if m[0] <= track['line'] <= m[1]:
          track['class'] = m[2]
          track['method'] = m[3]
          break
      #print track.get('class')
      if not track.get('class'):
        
        #print '[Error] failed to get class & method for track "%s"' % (track['track'],)

        continue
      all_tracks.append(track)

  return all_tracks


def find_tracks_in_source(filename):
  '''
  查找源代码文件内的打点类型、名称、行号
  '''
  global SYSTEM
  #适配UT5.0
  re_pattern_5 = re.compile(r'\[\[\[UTAnalytics\sgetInstance\].*\]\s+(\w+?):.*?:@"(.+?)"')  #只考虑了 withPageName:@"abcd" 未考虑 withPageName:self.name情况
  not_re_pattern_5 = re.compile(r'\/\/.*\[\[\[UTAnalytics\sgetInstance\]')
  valid_actions_5 = ['pageAppear', 'pageDisAppear']
  
  
  re_pattern = re.compile(r'\[UT\s+(\w+?):.*?@"(.+?)"') 
  not_re_pattern = re.compile(r'\/\/.*\[UT\s+')
  valid_not_re_pattern = re.compile(r'\[UT\s+(\w+?):.*?@"(.+?)".*\/\/.*\[UT\s+') #考虑[UT ctrlClicked:] //[UT ctrlClicked:] 情况
  begin_annotation = re.compile(r'\/\*.*') #考虑/*********/ 情况
  end_annotation = re.compile(r'\*\/')
  valid_actions = ['pageAppear', 'pageDisAppear', 'ctrlClicked', 'commitEvent','pageAppear', 'pageDisAppear']
  
  all_tracks = []

  # 用正则表达式逐行匹配UT调用
  with open(filename) as f:
    lines = f.readlines()
    ANNOTATION = 0
    for idx, line in enumerate(lines):
      if ANNOTATION == 1:
        continue
      if begin_annotation.search(line):
        ANNOTATION = 1
      if end_annotation.search(line):
        ANNOTATION = 0
      if ANNOTATION == 1: #注释第一行的情况考虑
        continue
      m = re_pattern.search(line)
      if not m:
        continue
      if not_re_pattern.search(line): #未考虑[UT ctrlClicked:] //[UT ctrlClicked:] 情况＊＊＊＊＊＊＊＊＊＊ 和/*********/情况
        '''考虑[UT ctrlClicked:] //[UT ctrlClicked:] 情况
        '''
        mm = valid_not_re_pattern.search(line)
        if mm:
          (action, param) = mm.groups()
          if action in valid_actions:
            if not param:
              print '[Warning] failed to parse UT call in file %s, line: %d' % (filename, idx + 1)
          else:
            all_tracks.append({'track': param.decode('utf-8'), 'type': action, 'file': filename, 'line': idx + 1})
        else:
          continue
        '''考虑[UT ctrlClicked:] //[UT ctrlClicked:] 情况
        '''
      (action, param) = m.groups()
      if action == 'pageEnter':
        action = 'pageAppear'
      if action == 'pageLeave':
        action = 'pageDisAppear'
      if action in valid_actions:
        if not param:
          print '[Warning] failed to parse UT call in file %s, line: %d' % (filename, idx + 1)
        else:
          all_tracks.append({'track': param.decode('utf-8'), 'type': action, 'file': filename, 'line': idx + 1})
  
  return all_tracks


def parse_methods_in_source(filename):
  
  '''
  通过clang解析源代码，得到文件内所有方法的行数范围
  返回数组包含文件内的方法列表 [(开始行号, 结束行号, class, method), ...]
  '''
  re_class_pattern = re.compile(r'(ObjCImplementationDecl|ObjCCategoryImplDecl).*\<.*\>[\s+-]*(\S+)\s(\S+)')
  re_method_pattern = re.compile(r'ObjCMethodDecl.*\<.*:(\d+):\d+.*:(\d+):\d+\>[\s+-]*(\S+)\s-\s(\S+)')

  all_methods = []

  # clang解析文件得到AST
  # clang -nostdinc -Xclang -ast-dump -fblocks -x objective-c xxx.m
  # -nostdinc 不查找系统头文件，否则#import <Foundation/Foundation.h>会导致奇慢无比
  # 如果代码中使用了一些宏，行末没有加分号，会导致clang解析失败。参考下面'-DSYNTHESIZE_SINGLETON_FOR_CLASS'
  
  cmdargs =  ['clang',
              '-Xclang',
              '-ast-dump',
              '-fblocks', '-x', 'objective-c',
              '-nostdinc',
              '-DSYNTHESIZE_SINGLETON_FOR_CLASS',   # 忽略这个宏，否则行末没有分号导致解析失败
              ]
  cmdargs.append(filename)
  FNULL = open(os.devnull, 'w')
  p = subprocess.Popen(cmdargs, stdout=subprocess.PIPE, stderr=FNULL)
  ast, _ = p.communicate()
  #print p
  # 去掉颜色代码
  ast = re.sub(r'\x1B\[[0-9;]*[mK]', '', ast)
  #print ast
  # 逐行匹配，找到方法定义所在的行号范围
  class_name = None
  for ast_line in ast.splitlines():
    #print ast_line
    m = re_class_pattern.search(ast_line)
    if m:
         
      class_name = m.group(3)   #group(2)为行数信息 line:11:11
      #print '额呵呵'
      #print class_name
    if not class_name:
      continue

    m = re_method_pattern.search(ast_line)
    if m:
      #print class_name  
      #print '哈哈'  
      #print m.group()
      #print m.groups()
      #print m.group(3)
      
      (begin, end, method_line, method_name) = m.groups()
      #print class_name
      #print (int(begin), int(end), class_name, method_name)
      all_methods.append((int(begin), int(end), class_name, method_name))  #原class_name,method_name仅为行号＊＊＊＊＊＊
      #print (int(begin), int(end), class_name, method_name)
  return all_methods


def compare_tracks(expected, actual):
  # json.dump(expected, open('/Users/wangxl/Desktop/1.json', 'w+'))
  # json.dump(actual, open('/Users/wangxl/Desktop/2.json', 'w+'))
  # return
  '''
  比较配置文件中的打点列表和源码中的打点列表，输出比较结果
  '''
  missing_tracks = list(expected)
  redundate_tracks = list(actual)
  wrong_tracks = []
  correct_tracks = []

  for t1 in expected:
    if t1['type'] == 'ctrlClicked' or t1['type'] == 'commitEvent':
      # 控件打点/自定义打点要检查类名方法名是否完全匹配
      name_match = False
      method_match = False
      best_match = None
      for t2 in redundate_tracks:
        if t1['track'] != t2['track'] or t1['type'] != t2['type']:
          continue

        name_match = True
        best_match = t2
        
        if t1['class'] == t2.get('class') and t1['method'] == t2.get('method'):
          method_match = True
          #print t1['class']
          #print t2.get('class')
          #print t1['method']   #改了位置仍相同。＊＊＊＊＊＊＊注释的没有去掉
          #print t2.get('method')
          correct_tracks.append(t1)
          missing_tracks.remove(t1)
          redundate_tracks.remove(t2)
          break

      # 如果track匹配，但方法不匹配的，则当做位置错误的打点
      if name_match and not method_match:
        wrong_tracks.append((t1, best_match))

    else:
      # 页面打点只检查track是否匹配
      for t2 in redundate_tracks:
        if t1['track'] == t2['track'] and t1['type'] == t2['type']:
          missing_tracks.remove(t1)
          redundate_tracks.remove(t2)
          break

  # 把漏打点/多余打点中所有的位置错误的情况过滤掉，等到修复了位置错误后，剩余的真正问题还会暴露出来
  for (t1, _) in wrong_tracks:
    for t2 in missing_tracks:
      if t1['track'] == t2['track'] and t1['type'] == t2['type']:
        try:
          missing_tracks.remove(t2)
        except ValueError:
          pass
        # no break
    for t2 in redundate_tracks:
      if t1['track'] == t2['track'] and t1['type'] == t2['type']:
        try:
          redundate_tracks.remove(t2)
        except ValueError:
          pass
        # no break

  # 输出信息
  print '\n==================\n遗漏的打点\n=================='
  if len(missing_tracks) > 0:
    for t in missing_tracks:
      page = t.get('page')
      if page:
        printUnicode(u'[UT %s:@"%s"] - 页面: %s, 说明: %s' \
                     % (t['type'], t['track'], page['name'], t['name']))
      else:
        printUnicode(u'[UT %s:@"%s"] - 说明: %s' % (t['type'], t['track'], t['name']))
      printUnicode(u'位置：类：%s ＋ 方法：%s' % (t.get('class'), t.get('method')))
      print
  else:
    print '（无）'

  print '\n==================\n位置错误的打点\n=================='
  if len(wrong_tracks) > 0:
    for (t, t2) in wrong_tracks:
      page = t.get('page')
      page_desc = (u'页面: %s,' % (page['name'],)) if page else ''
      method_desc = (u'\n期望位置: [%s %s]' % (t['class'], t['method']))
      actual_method_desc = (u'\n实际位置: [%s %s]' % (t2.get('class'), t2.get('method'))) if t2.get('class') else ''
      printUnicode(u'[UT %s:@"%s"] - %s 说明: %s %s %s' \
                   % (t['type'], t['track'], page_desc, t['name'], method_desc, actual_method_desc))
      print
  else:
    print '（无）'

  print '\n==================\n多余的打点\n=================='
  #print '（暂时不管）'
  if len(redundate_tracks) > 0:
    for t in redundate_tracks:
      filepath = os.path.relpath(t['file'])
      printUnicode(u'[UT %s:@"%s"] - 文件: %s, 行: %d' % (t['type'], t['track'], filepath, t['line']))
      print
  else:
    print '（无）'
    
  print '\n==================\n正确的打点\n=================='
  if len(correct_tracks) > 0:
    for t in correct_tracks:
      page = t.get('page')
      if page:
        printUnicode(u'[UT %s:@"%s"] - 页面: %s, 说明: %s' \
                     % (t['type'], t['track'], page['name'], t['name']))
      else:
        printUnicode(u'[UT %s:@"%s"] - 说明: %s' % (t['type'], t['track'], t['name']))
        
      printUnicode(u'位置：类：%s ＋ 方法：%s' % (t['class'], t['method']))
      print
  else:
    print '（无）'
  return len(missing_tracks) == 0 and len(wrong_tracks) == 0


def usage():
  print "功能：\n\t检查UT打点是否有遗漏。\n用法：\n\tpython usertrack_check.py <config file>"


def printUnicode(ustr):
  print ustr.encode('utf-8')


if __name__ == '__main__':
  if len(sys.argv) < 2:
    usage()
    initialize()
    download()
    check_with_config("usertrack_list.json")
  else:
    initialize()
    check_with_config(sys.argv[1])
    #TEST!
    # compare_tracks(json.load(open('/Users/wangxl/Desktop/1.json')), json.load(open('/Users/wangxl/Desktop/2.json')))
